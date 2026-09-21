"""Canonical identities for normalized trace evidence and annotation targets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from .canonical import canonical_sha256


def _json_value(value: Any) -> Any:
    """Return a JSON-mode Pydantic value without dropping meaningful defaults."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    return value


def _field(case_or_parts: Any, name: str) -> Any:
    if isinstance(case_or_parts, Mapping):
        return case_or_parts[name]
    return getattr(case_or_parts, name)


def normalized_case_evidence(case_or_parts: Any) -> dict[str, Any]:
    """Return the trace-only identity recipe used by new normalized artifacts.

    Constraints, labels, telemetry, and static repository context deliberately do
    not affect this identity. They are bound separately where required.
    """
    return {
        "agent": _json_value(_field(case_or_parts, "agent")),
        "task_user_request": _field(case_or_parts, "task_user_request"),
        "instruction_surfaces": _json_value(_field(case_or_parts, "instruction_surfaces")),
        "events": _json_value(_field(case_or_parts, "events")),
    }


def normalized_evidence_sha256(case_or_parts: Any) -> str:
    return canonical_sha256(normalized_case_evidence(case_or_parts))


def annotation_target_identity(case_or_parts: Any) -> dict[str, Any]:
    """Return the full non-label target a human annotation is allowed to bind."""
    return {
        "normalized_evidence": normalized_case_evidence(case_or_parts),
        "constraints": _json_value(_field(case_or_parts, "constraints")),
        "telemetry": _json_value(_field(case_or_parts, "telemetry")),
        "starting_repo_tree": _json_value(_field(case_or_parts, "starting_repo_tree")),
        "filesystem_case_sensitive": _json_value(
            _field(case_or_parts, "filesystem_case_sensitive")
        ),
    }


def annotation_target_sha256(case_or_parts: Any) -> str:
    return canonical_sha256(annotation_target_identity(case_or_parts))
