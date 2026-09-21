from __future__ import annotations

import json
from pathlib import Path

import pytest

from contract_eval.annotate import build_ground_truth, save_annotations
from contract_eval.annotations import (
    AnnotationArtifactError,
    annotation_set_sha256,
    load_annotation_artifacts,
    overlay_annotation_labels,
    validate_annotation_artifact,
)
from contract_eval.cli import load_case
from contract_eval.schema import AnnotationArtifact

CASE_PATH = Path(__file__).parents[1] / "fixtures" / "synthetic" / "dev-12-semantic-pending.json"


def test_bound_artifact_round_trips_and_validates(tmp_path: Path) -> None:
    case = load_case(CASE_PATH)
    label = build_ground_truth(case, "C1", {"outcome": "ungradeable", "annotation_method": "human"})
    output = save_annotations(tmp_path / "labels.json", case, {"C1": label})
    artifact = load_annotation_artifacts(output)[case.case_id]
    assert artifact.annotation_target_sha256 is not None
    validate_annotation_artifact(case, artifact)
    assert overlay_annotation_labels(case, artifact)["C1"].outcome == "ungradeable"
    assert annotation_set_sha256({case.case_id: artifact})


def test_unknown_human_label_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown"):
        AnnotationArtifact(
            case_id="x",
            case_evidence_sha256="a" * 64,
            annotation_target_sha256="b" * 64,
            labels={"C1": {"outcome": "unknown", "annotation_method": "human"}},
        )


def test_legacy_artifact_can_be_loaded_but_cannot_replace_placeholder(tmp_path: Path) -> None:
    case = load_case(CASE_PATH)
    legacy_hash = __import__(
        "contract_eval.canonical", fromlist=["canonical_sha256"]
    ).canonical_sha256(case.model_dump(mode="json", exclude={"labels"}, exclude_none=False))
    raw = {
        "schema_version": "1.0",
        "case_id": case.case_id,
        "case_source_sha256": case.source.raw_sha256,
        "case_evidence_sha256": legacy_hash,
        "annotation_method": "human",
        "labels": {"C1": {"outcome": "compliant", "annotation_method": "human"}},
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    artifact = load_annotation_artifacts(path)[case.case_id]
    assert artifact.legacy_unbound is True
    with pytest.raises(AnnotationArtifactError, match="legacy"):
        overlay_annotation_labels(case, artifact)


def test_duplicate_case_artifacts_are_rejected(tmp_path: Path) -> None:
    case = load_case(CASE_PATH)
    label = build_ground_truth(case, "C1", {"outcome": "compliant", "annotation_method": "human"})
    save_annotations(tmp_path / "one.json", case, {"C1": label})
    save_annotations(tmp_path / "two.json", case, {"C1": label})
    with pytest.raises(AnnotationArtifactError, match="duplicate"):
        load_annotation_artifacts(tmp_path)
