from __future__ import annotations

import json
from pathlib import Path

import pytest

from contract_eval.annotate import (
    AnnotationError,
    annotation_prompts,
    build_ground_truth,
    collect_annotation,
    interactive_answer,
    save_annotations,
)
from contract_eval.schema import Case, GroundTruth

FIXTURE = Path("fixtures/synthetic/dev-02-write-protected.json")


def load_case() -> Case:
    return Case.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def test_prompts_show_successive_prefixes_without_labels() -> None:
    case = load_case()
    constraint_id = case.constraints[0].id
    prompts = annotation_prompts(case, constraint_id)

    assert len(prompts) == len(case.events)
    assert len(prompts[-1].prefix_events) == len(case.events)
    assert all("labels" not in event for event in prompts[-1].prefix_events)
    assert prompts[-1].constraint_verbatim == case.constraints[0].verbatim


def test_build_ground_truth_rejects_unsupported_timing() -> None:
    case = load_case()
    constraint_id = case.constraints[0].id
    with pytest.raises(AnnotationError, match="unknown event"):
        build_ground_truth(
            case,
            constraint_id,
            {
                "outcome": "violated",
                "first_clear_violation_event": "future-not-in-case",
                "annotation_method": "human",
            },
        )


def test_annotations_require_notes_for_ambiguous_or_violated_outcomes_and_visit_prefixes() -> None:
    case = load_case()
    constraint_id = case.constraints[0].id
    with pytest.raises(AnnotationError, match="require evidence notes"):
        build_ground_truth(
            case,
            constraint_id,
            {
                "outcome": "ambiguous",
                "annotation_method": "human",
            },
        )
    seen: list[int] = []
    result = collect_annotation(
        case,
        constraint_id,
        lambda prompt: (
            seen.append(prompt.prefix_seq) or {"outcome": "compliant", "annotation_method": "human"}
        ),
        overwrite=True,
    )
    assert seen == [event.seq for event in case.events]
    assert result.outcome == "compliant"


def test_existing_fixture_label_requires_explicit_overwrite() -> None:
    case = load_case()
    constraint_id = next(iter(case.labels), case.constraints[0].id)
    if constraint_id not in case.labels:
        case = case.model_copy(
            update={
                "labels": {
                    constraint_id: GroundTruth(outcome="compliant", annotation_method="human")
                }
            }
        )
    with pytest.raises(AnnotationError, match="already has a label"):
        collect_annotation(
            case, constraint_id, lambda _: {"outcome": "compliant", "annotation_method": "human"}
        )


def test_save_annotations_is_separate_and_refuses_existing_output(tmp_path: Path) -> None:
    case = load_case()
    constraint_id = case.constraints[0].id
    label = build_ground_truth(
        case, constraint_id, {"outcome": "compliant", "annotation_method": "human"}
    )
    destination = save_annotations(tmp_path / "labels.json", case, {constraint_id: label})
    artifact = json.loads(destination.read_text(encoding="utf-8"))
    assert artifact["case_id"] == case.case_id
    assert artifact["case_source_sha256"] == case.source.raw_sha256
    assert len(artifact["case_evidence_sha256"]) == 64
    with pytest.raises(AnnotationError, match="output exists"):
        save_annotations(destination, case, {constraint_id: label})


def test_interactive_answer_collects_supported_timing_fields_once() -> None:
    case = load_case()
    prompt = annotation_prompts(case, case.constraints[0].id)[-1]
    answers = iter(
        [
            "violated",
            "command evidences the attempted dependency addition",
            "e1",
            "e1",
            "",
            "",
            "n",
        ]
    )
    answer = interactive_answer(prompt, lambda _: next(answers))
    assert answer["outcome"] == "violated"
    assert answer["first_clear_violation_event"] == "e1"
    assert answer["first_attempt_event"] == "e1"
    assert answer["first_effect_event"] is None
    assert answer["pre_effect_warning_possible"] is False
