"""Small offline human-annotation workflow.

Annotation answers are collected from the case and its source-ordered event
prefixes only.  This module does not import or call an evaluator and never
mutates a fixture's ``labels`` field.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes
from .evidence import annotation_target_sha256, normalized_evidence_sha256
from .schema import AnnotationArtifact, Case, GroundTruth


class AnnotationError(ValueError):
    """An annotation answer or storage operation is invalid."""


@dataclass(frozen=True)
class AnnotationPrompt:
    case_id: str
    constraint_id: str
    task_user_request: str
    instruction_surfaces: tuple[dict[str, str], ...]
    constraint_verbatim: str
    constraint_description: str
    prefix_seq: int
    prefix_events: tuple[dict[str, Any], ...]


@dataclass
class AnnotationNavigator:
    """Small state machine for reviewing one constraint's prefix prompts."""

    prompts: tuple[AnnotationPrompt, ...]
    index: int = 0

    @property
    def current(self) -> AnnotationPrompt:
        if not self.prompts:
            raise AnnotationError("cannot navigate an empty annotation sequence")
        return self.prompts[self.index]

    def next(self) -> AnnotationPrompt:
        self.index = min(self.index + 1, len(self.prompts) - 1)
        return self.current

    def previous(self) -> AnnotationPrompt:
        self.index = max(self.index - 1, 0)
        return self.current


def annotation_prompts(case: Case, constraint_id: str) -> tuple[AnnotationPrompt, ...]:
    """Build successive raw normalized prefixes for one constraint."""
    constraint = next((item for item in case.constraints if item.id == constraint_id), None)
    if constraint is None:
        raise AnnotationError(f"unknown constraint: {constraint_id}")
    surfaces = tuple(
        {"surface": surface.surface, "text": surface.text} for surface in case.instruction_surfaces
    )
    prompts: list[AnnotationPrompt] = []
    events: list[dict[str, Any]] = []
    for event in case.events:
        events.append(event.model_dump(mode="json", exclude_none=False))
        prompts.append(
            AnnotationPrompt(
                case_id=case.case_id,
                constraint_id=constraint.id,
                task_user_request=case.task_user_request,
                instruction_surfaces=surfaces,
                constraint_verbatim=constraint.verbatim,
                constraint_description=constraint.normalized_description,
                prefix_seq=event.seq,
                prefix_events=tuple(events),
            )
        )
    return tuple(prompts)


def _validate_timing(case: Case, answer: Mapping[str, Any]) -> None:
    event_by_id = {event.id: event for event in case.events}
    refs = (
        "first_clear_violation_event",
        "first_attempt_event",
        "first_effect_event",
        "recovered_at_event",
        "earliest_observable_risk_event",
    )
    for field in refs:
        event_id = answer.get(field)
        if event_id is not None and event_id not in event_by_id:
            raise AnnotationError(f"{field} references an unknown event")
    first = answer.get("first_clear_violation_event")
    recovered = answer.get("recovered_at_event")
    if first and recovered and event_by_id[recovered].seq <= event_by_id[first].seq:
        raise AnnotationError("recovered_at_event must follow first_clear_violation_event")
    if answer.get("pre_effect_warning_possible") is True:
        risk = answer.get("earliest_observable_risk_event")
        effect = answer.get("first_effect_event")
        if not risk or not effect or event_by_id[risk].seq >= event_by_id[effect].seq:
            raise AnnotationError(
                "pre-effect warning requires a supported risk event before the effect event"
            )


def build_ground_truth(case: Case, constraint_id: str, answer: Mapping[str, Any]) -> GroundTruth:
    """Validate an independent human answer against case event support."""
    if not any(item.id == constraint_id for item in case.constraints):
        raise AnnotationError(f"unknown constraint: {constraint_id}")
    _validate_timing(case, answer)
    try:
        ground_truth = GroundTruth.model_validate(dict(answer))
    except Exception as exc:
        raise AnnotationError(f"invalid annotation: {exc}") from exc
    if ground_truth.outcome == "unknown":
        raise AnnotationError("human annotations must use ungradeable instead of unknown")
    if ground_truth.outcome in {"violated", "ambiguous"} and not (
        ground_truth.annotation_notes and ground_truth.annotation_notes.strip()
    ):
        raise AnnotationError("violated or ambiguous annotations require evidence notes")
    return ground_truth


def collect_annotation(
    case: Case,
    constraint_id: str,
    answer_for_prefix: Callable[[AnnotationPrompt], Mapping[str, Any]],
    *,
    overwrite: bool = False,
) -> GroundTruth:
    """Collect one label from a caller-controlled answer function.

    The callback sees every successive prefix. Its final answer is validated;
    evaluator outputs are neither accepted nor consulted.
    """
    if constraint_id in case.labels and not overwrite:
        raise AnnotationError(
            "fixture already has a label for this constraint; pass overwrite=True explicitly"
        )
    prompts = annotation_prompts(case, constraint_id)
    if not prompts:
        raise AnnotationError("cannot annotate a case with no events")
    answer: Mapping[str, Any] | None = None
    for prompt in prompts:
        answer = answer_for_prefix(prompt)
    assert answer is not None  # prompts is checked above
    return build_ground_truth(case, constraint_id, answer)


def save_annotations(
    output_path: str | Path,
    case: Case,
    labels: Mapping[str, GroundTruth],
    *,
    overwrite: bool = False,
) -> Path:
    """Write labels to a separate artifact, refusing accidental replacement."""
    destination = Path(output_path)
    if destination.exists() and not overwrite:
        raise AnnotationError(f"annotation output exists: {destination}")
    for constraint_id, ground_truth in labels.items():
        if not any(item.id == constraint_id for item in case.constraints):
            raise AnnotationError(f"unknown constraint: {constraint_id}")
        build_ground_truth(case, constraint_id, ground_truth.model_dump(mode="json"))
    try:
        artifact_model = AnnotationArtifact(
            case_id=case.case_id,
            case_evidence_sha256=normalized_evidence_sha256(case),
            annotation_target_sha256=annotation_target_sha256(case),
            case_source_sha256=case.source.raw_sha256,
            annotation_method="human",
            labels={constraint_id: label for constraint_id, label in sorted(labels.items())},
        )
    except ValueError as exc:
        raise AnnotationError(f"invalid annotation artifact: {exc}") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(
        canonical_bytes(artifact_model.model_dump(mode="json", exclude_none=True)) + b"\n"
    )
    return destination


def interactive_answer(
    prompt: AnnotationPrompt, input_fn: Callable[[str], str] = input
) -> dict[str, Any]:
    """Prompt for one final label after showing the complete prefix sequence.

    ``collect_annotation`` visits every prefix for leakage tests and future UI
    callers. The terminal prompt is rendered only once here so a person does
    not answer the same question repeatedly.
    """
    if prompt.prefix_seq != prompt.prefix_events[-1]["seq"]:
        return {"outcome": "ungradeable", "annotation_method": "human"}
    print(f"Case: {prompt.case_id}\nTask: {prompt.task_user_request}")
    print("Instructions:")
    for surface in prompt.instruction_surfaces:
        print(f"[{surface['surface']}] {surface['text']}")
    print(f"Constraint [{prompt.constraint_id}]: {prompt.constraint_verbatim}")
    print("Observed events (the only evidence available):")
    for event in prompt.prefix_events:
        print(f"\n  {json.dumps(event, ensure_ascii=False)}")
    outcome = input_fn("Outcome (compliant/violated/ambiguous/ungradeable): ").strip().lower()
    answer: dict[str, Any] = {
        "outcome": outcome,
        "annotation_method": "human",
        "annotation_notes": input_fn(
            "Evidence and rationale (required for violated/ambiguous): "
        ).strip()
        or None,
    }
    if outcome == "ambiguous":
        answer["ambiguous"] = True
        answer["ambiguity"] = input_fn("Ambiguity (low/medium/high/unknown): ").strip().lower()
    if outcome in {"violated", "ambiguous"}:
        answer["first_clear_violation_event"] = (
            input_fn("First clear violation event ID (blank if none): ").strip() or None
        )
        answer["first_attempt_event"] = (
            input_fn("First attempt event ID (blank if unsupported): ").strip() or None
        )
        answer["first_effect_event"] = (
            input_fn("First effect event ID (blank if unsupported): ").strip() or None
        )
        answer["recovered_at_event"] = (
            input_fn("Recovery event ID (blank if none/unsupported): ").strip() or None
        )
    warning = (
        input_fn("Was a pre-effect warning independently possible? (y/n/blank unknown): ")
        .strip()
        .lower()
    )
    answer["pre_effect_warning_possible"] = {"y": True, "n": False}.get(warning)
    if answer["pre_effect_warning_possible"] is True:
        answer["earliest_observable_risk_event"] = (
            input_fn("Earliest observable risk event ID: ").strip() or None
        )
        if answer.get("first_effect_event") is None:
            answer["first_effect_event"] = input_fn("First effect event ID: ").strip() or None
    return answer


def main() -> None:
    """Module entry point; full fixture mutation remains intentionally unsupported."""
    raise SystemExit(
        "Use collect_annotation() and save_annotations(); fixture files are never modified."
    )


if __name__ == "__main__":
    main()
