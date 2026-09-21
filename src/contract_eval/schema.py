"""Versioned public records.  Cases hold labels; normalized events never do."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: Literal["1.0"] = "1.0"
SchemaVersion = Literal["1.0"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceKind(StrEnum):
    SYNTHETIC = "synthetic"
    PUBLIC = "public"
    CONTROLLED = "controlled"


class SourceProvenance(StrictModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    kind: SourceKind
    origin_uri: str | None = None
    license: str | None = None
    redistribution_allowed: bool | None = None
    raw_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    # Deprecated legacy normalized-evidence identity. New controlled imports also
    # carry the distinct raw-source and normalized-evidence identities below.
    raw_source_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    normalized_evidence_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    trace_format: str = Field(min_length=1)
    normalizer_version: str = Field(min_length=1)


class AgentProvenance(StrictModel):
    harness: str = Field(min_length=1)
    harness_version: str | None = None
    model: str | None = None
    repo: str | None = None
    base_commit: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)


class InstructionSurface(StrictModel):
    id: str | None = Field(default=None, min_length=1)
    surface: Literal["user", "developer", "system", "repo_policy", "harness"]
    event_id: str | None = None
    text: str = Field(min_length=1)
    precedence_rank: int | None = None
    resolution: Literal["active", "overridden", "conflicted_unresolved", "informational"] | None = (
        None
    )
    resolution_notes: str | None = None


class OracleSpec(StrictModel):
    kind: Literal["exact", "conservative", "partial", "human", "mixed", "none"]
    implementation: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    limitations: tuple[str, ...] = ()


class ConstraintStatusTransition(StrictModel):
    event_id: str = Field(min_length=1)
    status: Literal["active", "overridden", "conflicted_unresolved"]
    resolution_notes: str | None = None


class Constraint(StrictModel):
    id: str = Field(min_length=1)
    verbatim: str = Field(min_length=1)
    normalized_description: str = Field(min_length=1)
    category: str = Field(min_length=1)
    provenance: Literal["user", "developer", "system", "repo_policy", "harness"]
    oracle: OracleSpec
    instruction_surface_id: str | None = Field(default=None, min_length=1)
    introduced_at_event_id: str | None = Field(default=None, min_length=1)
    # Initial status only. Later changes are represented by ordered transitions.
    status: Literal["active", "overridden", "conflicted_unresolved"] = "active"
    resolution_notes: str | None = None
    status_transitions: tuple[ConstraintStatusTransition, ...] = ()


class FileChange(StrictModel):
    path: str | None = None
    kind: Literal["create", "write", "delete", "unknown"] = "unknown"
    diff: str | None = None
    path_ambiguous: bool = False


class TelemetryCapabilities(StrictModel):
    file_changes_observed: bool | None = None
    file_change_completeness: Literal["complete", "partial", "unknown"] = "unknown"
    command_text_completeness: Literal["complete", "partial", "unknown"] = "unknown"
    network_events_observed: bool | None = None
    network_event_completeness: Literal["complete", "partial", "unknown"] = "unknown"
    pre_effect_boundary_verified: bool | None = None


class Event(StrictModel):
    id: str = Field(min_length=1)
    seq: int = Field(ge=1)
    kind: Literal[
        "instruction",
        "agent_message",
        "reasoning_summary",
        "plan_update",
        "file_read",
        "file_write",
        "file_create",
        "file_delete",
        "file_change",
        "command_start",
        "command_end",
        "tool_start",
        "tool_end",
        "mcp_call",
        "web_search",
        "test_run",
        "git_operation",
        "state_snapshot",
        "error",
        "unknown",
    ]
    actor: Literal["user", "developer", "system", "agent", "tool", "environment", "unknown"] = (
        "unknown"
    )
    tool: str | None = None
    status: Literal["started", "completed", "failed", "unknown"] = "unknown"
    side_effect: Literal["read", "write", "delete", "network", "none", "unknown"] = "unknown"
    path: str | None = None
    command: str | None = None
    arguments: dict[str, Any] | None = None
    text: str | None = None
    result_summary: str | None = None
    timestamp: str | None = None
    raw_ref: str | None = None
    path_ambiguous: bool = False
    source_metadata: dict[str, Any] | None = None
    changes: tuple[FileChange, ...] = ()
    effect_observation: Literal["source_reported", "normalizer_inferred", "unknown"] = "unknown"


class GroundTruth(StrictModel):
    outcome: Literal["compliant", "violated", "ungradeable", "unknown", "ambiguous"]
    first_clear_violation_event: str | None = None
    first_attempt_event: str | None = None
    first_effect_event: str | None = None
    recovered_at_event: str | None = None
    earliest_observable_risk_event: str | None = None
    pre_effect_warning_possible: bool | None = None
    ambiguous: bool = False
    ambiguity: Literal["low", "medium", "high", "unknown"] = "unknown"
    annotation_method: str = Field(min_length=1)
    annotation_notes: str | None = None


class AnnotationArtifact(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1)
    case_evidence_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    annotation_target_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    # Retained only to load artifacts emitted by the pre-bound annotator.
    case_source_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    annotation_method: Literal["human"] = "human"
    annotator_id: str | None = None
    annotated_at: str | None = None
    labels: dict[str, GroundTruth]
    legacy_unbound: bool = False

    @model_validator(mode="after")
    def validate_human_labels(self) -> AnnotationArtifact:
        if any(label.outcome == "unknown" for label in self.labels.values()):
            raise ValueError("human annotation cannot use unknown; use ungradeable")
        return self


class Case(StrictModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    case_id: str = Field(min_length=1)
    source: SourceProvenance
    agent: AgentProvenance
    task_user_request: str = Field(min_length=1)
    instruction_surfaces: tuple[InstructionSurface, ...] = Field(min_length=1)
    constraints: tuple[Constraint, ...] = Field(min_length=1)
    events: tuple[Event, ...]
    labels: dict[str, GroundTruth] = Field(default_factory=dict)
    telemetry: TelemetryCapabilities = Field(default_factory=TelemetryCapabilities)
    starting_repo_tree: tuple[str, ...] = ()
    filesystem_case_sensitive: bool | None = None

    @model_validator(mode="after")
    def validate_references(self) -> Case:
        ids = [event.id for event in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("event IDs must be unique")
        seqs = [event.seq for event in self.events]
        if seqs != sorted(seqs) or len(seqs) != len(set(seqs)):
            raise ValueError("event sequence must be strictly increasing")
        constraint_ids = {constraint.id for constraint in self.constraints}
        if len(constraint_ids) != len(self.constraints):
            raise ValueError("constraint IDs must be unique")
        if set(self.labels) - constraint_ids:
            raise ValueError("labels reference unknown constraints")
        event_ids = set(ids)
        event_seq = {event.id: event.seq for event in self.events}
        surface_ids = [
            surface.id for surface in self.instruction_surfaces if surface.id is not None
        ]
        if len(surface_ids) != len(set(surface_ids)):
            raise ValueError("instruction surface IDs must be unique")
        surfaces_by_id = {
            surface.id: surface for surface in self.instruction_surfaces if surface.id is not None
        }
        for surface in self.instruction_surfaces:
            if surface.event_id is not None and surface.event_id not in event_ids:
                raise ValueError("instruction surface references an unknown event")
            if surface.resolution == "conflicted_unresolved" and not (
                surface.resolution_notes and surface.resolution_notes.strip()
            ):
                raise ValueError("unresolved instruction surface needs resolution notes")
        available_surfaces = {surface.surface for surface in self.instruction_surfaces}
        for constraint in self.constraints:
            if constraint.provenance not in available_surfaces:
                raise ValueError("constraint provenance has no matching instruction surface")
            if not any(
                surface.surface == constraint.provenance
                and constraint.verbatim.casefold() in surface.text.casefold()
                for surface in self.instruction_surfaces
            ):
                raise ValueError("constraint verbatim text is absent from its instruction surface")
            if constraint.status == "conflicted_unresolved" and not (
                constraint.resolution_notes and constraint.resolution_notes.strip()
            ):
                raise ValueError("unresolved constraint needs resolution notes")
            bound_surface = (
                surfaces_by_id.get(constraint.instruction_surface_id)
                if constraint.instruction_surface_id is not None
                else None
            )
            if constraint.instruction_surface_id is not None and bound_surface is None:
                raise ValueError("constraint references an unknown instruction surface")
            if constraint.introduced_at_event_id is not None and (
                constraint.introduced_at_event_id not in event_ids
            ):
                raise ValueError("constraint references an unknown introduction event")
            if constraint.introduced_at_event_id is not None and bound_surface is None:
                raise ValueError("late constraint needs an instruction surface ID")
            if bound_surface is not None:
                if bound_surface.surface != constraint.provenance:
                    raise ValueError("constraint provenance differs from bound instruction surface")
                if constraint.verbatim.casefold() not in bound_surface.text.casefold():
                    raise ValueError(
                        "constraint verbatim text is absent from bound instruction surface"
                    )
                if bound_surface.event_id != constraint.introduced_at_event_id:
                    raise ValueError("constraint introduction must match bound instruction surface")
            transition_ids = [transition.event_id for transition in constraint.status_transitions]
            if len(transition_ids) != len(set(transition_ids)):
                raise ValueError("constraint status transitions must reference unique events")
            previous_seq = (
                event_seq[constraint.introduced_at_event_id]
                if constraint.introduced_at_event_id is not None
                else 0
            )
            for transition in constraint.status_transitions:
                if transition.event_id not in event_ids:
                    raise ValueError("constraint status transition references an unknown event")
                if event_seq[transition.event_id] < previous_seq:
                    raise ValueError("constraint status transitions must be source ordered")
                if transition.status == "conflicted_unresolved" and not (
                    transition.resolution_notes and transition.resolution_notes.strip()
                ):
                    raise ValueError("unresolved constraint transition needs resolution notes")
                previous_seq = event_seq[transition.event_id]
        for label in self.labels.values():
            refs = (
                label.first_clear_violation_event,
                label.first_attempt_event,
                label.first_effect_event,
                label.recovered_at_event,
                label.earliest_observable_risk_event,
            )
            if any(ref is not None and ref not in event_ids for ref in refs):
                raise ValueError("ground truth references an unknown event")
            if label.outcome == "violated" and label.first_clear_violation_event is None:
                raise ValueError("violated ground truth needs first_clear_violation_event")
            if label.outcome == "compliant" and any(
                (
                    label.first_clear_violation_event,
                    label.first_attempt_event,
                    label.first_effect_event,
                )
            ):
                raise ValueError("compliant ground truth cannot include violation timing")
            recovered_at = label.recovered_at_event
            first_clear = label.first_clear_violation_event
            if recovered_at and not first_clear:
                raise ValueError("recovery requires a first clear violation")
            if recovered_at and first_clear and ids.index(recovered_at) <= ids.index(first_clear):
                raise ValueError("recovery must follow first clear violation")
            if label.pre_effect_warning_possible:
                if not label.earliest_observable_risk_event or not label.first_effect_event:
                    raise ValueError("pre-effect warning requires risk and effect event references")
                if ids.index(label.earliest_observable_risk_event) >= ids.index(
                    label.first_effect_event
                ):
                    raise ValueError("risk event must precede effect for a pre-effect warning")
        return self


class EvaluatorConfig(StrictModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    evaluator_type: str = Field(min_length=1)
    implementation_version: str = Field(min_length=1)
    model_id: str | None = None
    question_spec_version: str = Field(min_length=1)
    projection_version: str = Field(min_length=1)
    event_selection_version: str = Field(default="all-observed-v1", min_length=1)
    threshold: float | None = Field(default=None, ge=0, le=1)


class EvaluationResult(StrictModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    case_id: str = Field(min_length=1)
    constraint_id: str = Field(min_length=1)
    prefix_seq: int = Field(ge=0)
    evaluator: EvaluatorConfig
    decision: Literal["alert", "no_alert", "abstain"]
    score: float | None = Field(default=None, ge=0, le=1)
    state_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    raw_response_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    call_id: str | None = None
    provider_call_made: bool | None = None
    from_cache: bool | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    latency_seconds: float | None = Field(default=None, ge=0)
    error_code: str | None = None


class DatasetManifest(StrictModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    dataset_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    case_ids: tuple[str, ...] = Field(min_length=1)
    source_provenance: tuple[SourceProvenance, ...] = Field(min_length=1)
    split: Literal["development", "evaluation", "holdout"]

    @model_validator(mode="after")
    def unique_cases(self) -> DatasetManifest:
        if len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("manifest case IDs must be unique")
        return self


class RunCaseIdentity(StrictModel):
    case_id: str = Field(min_length=1)
    case_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )


class RunManifest(StrictModel):
    """Typed immutable identity for one stored evaluation run."""

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(min_length=1)
    run_kind: str = Field(min_length=1)
    created_at_utc: str = Field(min_length=1)
    dataset_id: str | None = None
    dataset_manifest_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    evaluator: EvaluatorConfig
    evaluator_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    evaluator_spec_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    representation: str = Field(min_length=1)
    event_selection_version: str = Field(min_length=1)
    package_version: str | None = None
    python_version: str = Field(min_length=1)
    git_commit: str | None = None
    network_allowed: bool
    provider_call_count: int = Field(ge=0)
    cache_hit_count: int = Field(ge=0)
    cache_miss_count: int = Field(ge=0)
    cases: tuple[RunCaseIdentity, ...] = Field(min_length=1)
    row_count: int = Field(ge=0)
    rows_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def unique_case_ids(self) -> RunManifest:
        ids = [item.case_id for item in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("run manifest case IDs must be unique")
        return self


def validate_run_manifest_bindings(
    manifest: RunManifest,
    *,
    row_count: int,
    rows_sha256: str,
    case_identities: tuple[RunCaseIdentity, ...] | None = None,
) -> None:
    """Validate stored row and case identities before report generation."""
    if row_count != manifest.row_count:
        raise ValueError("run manifest row count mismatch")
    if rows_sha256 != manifest.rows_sha256:
        raise ValueError("run manifest row hash mismatch")
    if case_identities is not None and tuple(case_identities) != manifest.cases:
        raise ValueError("run manifest case identities mismatch")
