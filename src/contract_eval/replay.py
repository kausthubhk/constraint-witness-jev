"""Construction of evaluator-visible, prefix-only state."""

from __future__ import annotations

from typing import Literal

from .canonical import canonical_sha256
from .schema import Case, Constraint, Event, TelemetryCapabilities

_EVENT_FIELDS = (
    "id",
    "seq",
    "kind",
    "actor",
    "tool",
    "status",
    "side_effect",
    "path",
    "command",
    "arguments",
    "text",
    "result_summary",
    "timestamp",
    "path_ambiguous",
)

Representation = Literal[
    "normalized_raw",
    "policy_projection_v1",
    "normalized_raw_v2",
    "policy_projection_v2",
]

_POLICY_EVENT_FIELDS = (
    "id",
    "seq",
    "kind",
    "actor",
    "tool",
    "status",
    "side_effect",
    "path",
    "command",
    "path_ambiguous",
)

_V2_EVENT_FIELDS = _EVENT_FIELDS + ("changes", "effect_observation")
_V2_POLICY_EVENT_FIELDS = _POLICY_EVENT_FIELDS + ("changes", "effect_observation")


def requires_v2_representation(case: Case) -> bool:
    """Whether a case contains evidence V1 semantic replay must not omit.

    Callers selecting a frozen V1 semantic evaluator must reject these cases
    before cache lookup. Deterministic evaluation and annotation may still use
    the case and V2 representations.
    """
    if case.telemetry != TelemetryCapabilities():
        return True
    if any(
        event.kind == "file_change" or event.changes or event.effect_observation != "unknown"
        for event in case.events
    ):
        return True
    if any(
        surface.id is not None
        or surface.event_id is not None
        or surface.precedence_rank is not None
        or surface.resolution is not None
        or surface.resolution_notes is not None
        for surface in case.instruction_surfaces
    ):
        return True
    return any(
        constraint.instruction_surface_id is not None
        or constraint.introduced_at_event_id is not None
        or constraint.status != "active"
        or constraint.resolution_notes is not None
        or constraint.status_transitions
        for constraint in case.constraints
    )


def prefix_events(events: tuple[Event, ...], through_seq: int) -> tuple[Event, ...]:
    """Return source-ordered events available through the declared event sequence."""
    if through_seq < 0:
        raise ValueError("through_seq must be non-negative")
    return tuple(event for event in events if event.seq <= through_seq)


def _effective_constraint_status(constraint: Constraint, case: Case, through_seq: int) -> str:
    status = constraint.status
    seq_by_id = {event.id: event.seq for event in case.events}
    for transition in constraint.status_transitions:
        if seq_by_id[transition.event_id] <= through_seq:
            status = transition.status
        else:
            break
    return status


def _visible_constraints(case: Case, through_seq: int) -> list[Constraint]:
    seq_by_id = {event.id: event.seq for event in case.events}
    visible: list[Constraint] = []
    for constraint in case.constraints:
        introduced = constraint.introduced_at_event_id
        if introduced is not None and seq_by_id[introduced] > through_seq:
            continue
        if _effective_constraint_status(constraint, case, through_seq) == "active":
            visible.append(constraint)
    return visible


def _visible_instruction_surfaces(case: Case, through_seq: int):
    seq_by_id = {event.id: event.seq for event in case.events}
    return tuple(
        surface
        for surface in case.instruction_surfaces
        if surface.event_id is None or seq_by_id[surface.event_id] <= through_seq
    )


def evaluator_state(
    case: Case, through_seq: int, representation: Representation = "normalized_raw"
) -> dict[str, object]:
    """Build one versioned, evaluator-visible prefix representation.

    ``normalized_raw`` is the compatibility representation: it keeps every
    normalized, allowlisted event field. ``policy_projection_v1`` keeps the
    same prefix and context but strips free-form event payload fields. Both
    deliberately exclude labels, case/source identity, raw references, and
    source metadata; neither representation summarizes later events.
    """
    if representation not in {
        "normalized_raw",
        "policy_projection_v1",
        "normalized_raw_v2",
        "policy_projection_v2",
    }:
        raise ValueError(f"unsupported evaluator representation {representation}")
    events = prefix_events(case.events, through_seq)
    is_v2 = representation in {"normalized_raw_v2", "policy_projection_v2"}
    constraints = [
        {
            "verbatim": c.verbatim,
            "normalized_description": c.normalized_description,
            "category": c.category,
            "provenance": c.provenance,
        }
        for c in _visible_constraints(case, through_seq)
    ]
    event_fields: tuple[str, ...]
    if representation == "normalized_raw":
        event_fields = _EVENT_FIELDS
    elif representation == "policy_projection_v1":
        event_fields = _POLICY_EVENT_FIELDS
    elif representation == "normalized_raw_v2":
        event_fields = _V2_EVENT_FIELDS
    else:
        event_fields = _V2_POLICY_EVENT_FIELDS
    state: dict[str, object] = {
        "schema_version": "1.0",
        "task_user_request": case.task_user_request,
        "instruction_surfaces": [
            {"surface": surface.surface, "text": surface.text}
            for surface in _visible_instruction_surfaces(case, through_seq)
        ],
        "constraints": constraints,
        "static_context": {
            "starting_repo_tree": getattr(case, "starting_repo_tree", {}),
            "filesystem_case_sensitive": getattr(case, "filesystem_case_sensitive", None),
        },
        "events": [{field: getattr(event, field) for field in event_fields} for event in events],
    }
    # Preserve the existing normalized_raw serialization. The projection
    # identifies itself inside the hashed state because its fields differ.
    if representation in {"policy_projection_v1", "normalized_raw_v2", "policy_projection_v2"}:
        state["representation"] = representation
    if is_v2:
        state["telemetry"] = case.telemetry.model_dump(mode="json", exclude_none=False)
    return state


def evaluator_state_sha256(
    case: Case, through_seq: int, representation: Representation = "normalized_raw"
) -> str:
    """Hash the exact selected representation, including its version identifier."""
    return canonical_sha256(evaluator_state(case, through_seq, representation))
