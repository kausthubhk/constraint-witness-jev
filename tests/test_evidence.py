from contract_eval.evidence import annotation_target_sha256, normalized_evidence_sha256
from contract_eval.schema import (
    AgentProvenance,
    Case,
    Constraint,
    Event,
    InstructionSurface,
    OracleSpec,
    SourceProvenance,
    TelemetryCapabilities,
)


def _case(*, task: str = "fix", telemetry: TelemetryCapabilities | None = None) -> Case:
    return Case(
        case_id="evidence",
        source=SourceProvenance(
            kind="synthetic", raw_sha256="a" * 64, trace_format="synthetic", normalizer_version="1"
        ),
        agent=AgentProvenance(harness="synthetic"),
        task_user_request=task,
        instruction_surfaces=(InstructionSurface(surface="user", text="Do not edit tests."),),
        constraints=(
            Constraint(
                id="C1",
                verbatim="Do not edit tests.",
                normalized_description="protect tests",
                category="write_scope",
                provenance="user",
                oracle=OracleSpec(kind="exact", implementation="path_write_deny"),
            ),
        ),
        events=(Event(id="e1", seq=1, kind="file_read", path="src/a.py"),),
        telemetry=telemetry or TelemetryCapabilities(),
    )


def test_trace_identity_ignores_annotation_target_fields() -> None:
    baseline = _case()
    changed = _case(telemetry=TelemetryCapabilities(file_change_completeness="complete"))
    assert normalized_evidence_sha256(baseline) == normalized_evidence_sha256(changed)
    assert annotation_target_sha256(baseline) != annotation_target_sha256(changed)


def test_trace_identity_changes_when_event_evidence_changes() -> None:
    baseline = _case()
    changed = baseline.model_copy(
        update={"events": (Event(id="e1", seq=1, kind="file_read", path="src/b.py"),)}
    )
    assert normalized_evidence_sha256(baseline) != normalized_evidence_sha256(changed)
