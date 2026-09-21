from __future__ import annotations

import pytest
from pydantic import ValidationError

from contract_eval.schema import (
    AgentProvenance,
    Case,
    Constraint,
    ConstraintStatusTransition,
    Event,
    FileChange,
    GroundTruth,
    InstructionSurface,
    OracleSpec,
    SourceProvenance,
    TelemetryCapabilities,
)


def source() -> SourceProvenance:
    return SourceProvenance(
        kind="synthetic",
        license="CC0-1.0",
        raw_sha256="a" * 64,
        trace_format="synthetic-v1",
        normalizer_version="0.1.0",
    )


def constraint() -> Constraint:
    return Constraint(
        id="C1",
        verbatim="do not edit tests",
        normalized_description="Protect tests",
        category="write_scope",
        provenance="user",
        oracle=OracleSpec(
            kind="exact", implementation="path_write_deny", config={"patterns": ["tests/**"]}
        ),
    )


def case_fields() -> dict:
    return {
        "agent": AgentProvenance(harness="synthetic"),
        "instruction_surfaces": (
            InstructionSurface(surface="user", text="fix; do not edit tests"),
        ),
    }


def test_case_requires_monotonic_unique_events_and_known_label_refs() -> None:
    base = dict(
        source=source(), task_user_request="fix", constraints=(constraint(),), **case_fields()
    )
    with pytest.raises(ValidationError, match="strictly increasing"):
        Case(
            case_id="x",
            events=(Event(id="a", seq=2, kind="file_read"), Event(id="b", seq=1, kind="file_read")),
            **base,
        )
    with pytest.raises(ValidationError, match="unknown event"):
        Case(
            case_id="x",
            events=(),
            labels={
                "C1": GroundTruth(
                    outcome="violated", first_effect_event="later", annotation_method="exact"
                )
            },
            **base,
        )


def test_case_rejects_unknown_constraint_label() -> None:
    with pytest.raises(ValidationError, match="unknown constraints"):
        Case(
            case_id="x",
            source=source(),
            task_user_request="fix",
            constraints=(constraint(),),
            events=(),
            **case_fields(),
            labels={"C2": GroundTruth(outcome="compliant", annotation_method="exact")},
        )


def test_compliant_label_cannot_claim_a_violation_timing() -> None:
    base = dict(
        source=source(), task_user_request="fix", constraints=(constraint(),), **case_fields()
    )
    with pytest.raises(ValidationError, match="cannot include violation timing"):
        Case(
            case_id="x",
            events=(Event(id="e1", seq=1, kind="file_write"),),
            labels={
                "C1": GroundTruth(
                    outcome="compliant", first_effect_event="e1", annotation_method="exact"
                )
            },
            **base,
        )


def test_schema_models_reject_unknown_fields_and_allow_no_deterministic_oracle() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Event(id="e1", seq=1, kind="unknown", future_derived=True)
    semantic = Constraint(
        id="semantic",
        verbatim="preserve backward compatibility",
        normalized_description="preserve public behavior",
        category="semantic",
        provenance="user",
        oracle=OracleSpec(kind="none", implementation="human_review"),
    )
    assert semantic.oracle.kind == "none"


def test_additive_provenance_and_file_change_fields_validate() -> None:
    provenance = source().model_copy(
        update={
            "raw_source_sha256": "b" * 64,
            "normalized_evidence_sha256": "c" * 64,
        }
    )
    event = Event(
        id="e1",
        seq=1,
        kind="file_change",
        status="completed",
        changes=(FileChange(path="src/a.py", kind="write"),),
        effect_observation="source_reported",
    )
    assert provenance.raw_source_sha256 == "b" * 64
    assert event.changes[0].path == "src/a.py"


def test_late_constraint_and_transition_references_are_validated() -> None:
    late_surface = InstructionSurface(
        id="late-user",
        surface="user",
        event_id="e1",
        text="Do not edit tests.",
    )
    late_constraint = constraint().model_copy(
        update={
            "instruction_surface_id": "late-user",
            "introduced_at_event_id": "e1",
            "status_transitions": (ConstraintStatusTransition(event_id="e2", status="overridden"),),
        }
    )
    case = Case(
        case_id="late",
        source=source(),
        task_user_request="fix",
        instruction_surfaces=(late_surface,),
        constraints=(late_constraint,),
        events=(
            Event(id="e1", seq=1, kind="instruction"),
            Event(id="e2", seq=2, kind="instruction"),
        ),
        agent=AgentProvenance(harness="synthetic"),
        telemetry=TelemetryCapabilities(),
    )
    assert case.constraints[0].status_transitions[0].status == "overridden"
    with pytest.raises(ValidationError, match="unknown introduction event"):
        Case(
            case_id="bad-late",
            source=source(),
            task_user_request="fix",
            instruction_surfaces=(late_surface,),
            constraints=(late_constraint.model_copy(update={"introduced_at_event_id": "missing"}),),
            events=(Event(id="e1", seq=1, kind="instruction"),),
            agent=AgentProvenance(harness="synthetic"),
        )
