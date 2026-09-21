"""Independent annotation artifact loading and deterministic label overlays."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from .canonical import canonical_sha256
from .evidence import annotation_target_sha256, normalized_evidence_sha256
from .schema import AnnotationArtifact, Case, GroundTruth


class AnnotationArtifactError(ValueError):
    """An annotation artifact is malformed, stale, or conflicts with a case."""


def _paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(item for item in path.glob("*.json") if item.is_file())
    raise AnnotationArtifactError(f"annotation path does not exist: {path}")


def load_annotation_artifacts(path: Path | str) -> dict[str, AnnotationArtifact]:
    """Load one artifact or a directory of artifacts, rejecting duplicate cases."""
    loaded: dict[str, AnnotationArtifact] = {}
    for item in _paths(Path(path)):
        try:
            raw = json.loads(item.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("artifact must be an object")
            legacy = "annotation_target_sha256" not in raw
            if legacy:
                # Legacy artifacts are parsed only after explicitly marking their
                # unbound status; case-specific hash validation happens below.
                raw = {**raw, "legacy_unbound": True}
            artifact = AnnotationArtifact.model_validate(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise AnnotationArtifactError(f"invalid annotation artifact {item}: {exc}") from exc
        if artifact.case_id in loaded:
            raise AnnotationArtifactError(f"duplicate annotation case ID: {artifact.case_id}")
        loaded[artifact.case_id] = artifact
    return loaded


def validate_annotation_artifact(
    case: Case,
    artifact: AnnotationArtifact,
    *,
    allow_legacy: bool = True,
) -> None:
    """Validate hashes and constraint/event references against a loaded case."""
    if artifact.case_id != case.case_id:
        raise AnnotationArtifactError("annotation case ID does not match case")
    if artifact.legacy_unbound and not allow_legacy:
        raise AnnotationArtifactError("legacy annotation artifact is not accepted here")
    if artifact.legacy_unbound:
        legacy_hash = canonical_sha256(
            case.model_dump(mode="json", exclude={"labels"}, exclude_none=False)
        )
        if artifact.case_evidence_sha256 != legacy_hash:
            raise AnnotationArtifactError("legacy annotation evidence hash mismatch")
    else:
        if artifact.case_evidence_sha256 != normalized_evidence_sha256(case):
            raise AnnotationArtifactError("annotation evidence hash mismatch")
        if artifact.annotation_target_sha256 != annotation_target_sha256(case):
            raise AnnotationArtifactError("annotation target hash mismatch")
    constraint_ids = {constraint.id for constraint in case.constraints}
    for constraint_id, label in artifact.labels.items():
        if constraint_id not in constraint_ids:
            raise AnnotationArtifactError(
                f"annotation references unknown constraint: {constraint_id}"
            )
        if label.outcome == "unknown":
            raise AnnotationArtifactError("human annotation cannot use unknown; use ungradeable")
        event_ids = {event.id for event in case.events}
        refs = (
            label.first_clear_violation_event,
            label.first_attempt_event,
            label.first_effect_event,
            label.recovered_at_event,
            label.earliest_observable_risk_event,
        )
        if any(ref is not None and ref not in event_ids for ref in refs):
            raise AnnotationArtifactError("annotation references an unknown event")


def overlay_annotation_labels(
    case: Case,
    artifact: AnnotationArtifact,
    *,
    allow_legacy: bool = True,
) -> dict[str, GroundTruth]:
    """Return effective labels without mutating the case or its fixture."""
    validate_annotation_artifact(case, artifact, allow_legacy=allow_legacy)
    effective = dict(case.labels)
    for constraint_id, label in artifact.labels.items():
        existing = effective.get(constraint_id)
        if existing is None:
            effective[constraint_id] = label
            continue
        if existing.annotation_method == "pending_human_review":
            if artifact.legacy_unbound:
                raise AnnotationArtifactError("legacy artifact cannot replace a placeholder label")
            effective[constraint_id] = label
            continue
        raise AnnotationArtifactError(
            f"annotation collides with finalized label: {case.case_id}/{constraint_id}"
        )
    return effective


def annotation_set_sha256(artifacts: Mapping[str, AnnotationArtifact]) -> str:
    """Hash canonical artifact identities for report provenance."""
    return canonical_sha256(
        [
            artifact.model_dump(mode="json", exclude={"legacy_unbound"})
            for _, artifact in sorted(artifacts.items())
        ]
    )


def overlay_annotation_set(
    case: Case,
    artifacts: Iterable[AnnotationArtifact],
    *,
    allow_legacy: bool = True,
) -> dict[str, GroundTruth]:
    """Apply at most one artifact for this case using the same collision rules."""
    selected = [artifact for artifact in artifacts if artifact.case_id == case.case_id]
    if len(selected) > 1:
        raise AnnotationArtifactError(f"multiple annotation artifacts for case: {case.case_id}")
    return (
        dict(case.labels)
        if not selected
        else overlay_annotation_labels(case, selected[0], allow_legacy=allow_legacy)
    )
