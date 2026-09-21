"""Offline evaluator arms over one prefix.

These helpers never perform semantic-model transport.  A caller may provide a
previously validated cached semantic decision to the hybrid arm; cache lookup,
question specifications, and threshold selection remain outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from .canonical import canonical_sha256
from .jev import JevEvaluator, OfflineCacheMiss, extract_scores
from .oracles import OracleDecision, evaluate_constraint, normalize_repo_path
from .replay import (
    Representation,
    evaluator_state,
    evaluator_state_sha256,
    prefix_events,
    requires_v2_representation,
)
from .schema import Case, Constraint, Event, TelemetryCapabilities

Decision = Literal["alert", "no_alert", "abstain"]
Route = Literal["deterministic", "heuristic", "hybrid_deterministic", "hybrid_semantic"]


class _UseCaseTelemetry:
    """Private sentinel distinguishing omitted telemetry from explicit ``None``."""


_USE_CASE_TELEMETRY = _UseCaseTelemetry()
TelemetrySelection = TelemetryCapabilities | None | _UseCaseTelemetry


@dataclass(frozen=True)
class CachedSemanticDecision:
    """A semantic result already associated with its exact prefix representation."""

    state_sha256: str
    representation: Representation
    decision: Decision
    score: float | None = None
    raw_response_sha256: str | None = None


@dataclass(frozen=True)
class ArmResult:
    decision: Decision
    route: Route
    skip_reason: str | None
    score: float | None = None
    oracle_outcome: str | None = None
    oracle_support: str | None = None
    state_sha256: str | None = None
    raw_response_sha256: str | None = None


def _oracle_result(decision: OracleDecision, *, route: Route) -> ArmResult:
    mapped: Decision
    if decision.outcome == "violated":
        mapped = "alert"
    elif decision.outcome == "compliant":
        mapped = "no_alert"
    else:
        mapped = "abstain"
    return ArmResult(
        decision=mapped,
        route=route,
        skip_reason=None,
        score=1.0 if mapped == "alert" else 0.0 if mapped == "no_alert" else None,
        oracle_outcome=decision.outcome,
        oracle_support=decision.support,
    )


def evaluate_deterministic(
    case: Case,
    constraint: Constraint,
    through_seq: int,
    *,
    telemetry: TelemetrySelection = _USE_CASE_TELEMETRY,
) -> ArmResult:
    """Run the case-specific oracle on the prefix without consulting labels."""
    resolved_telemetry: TelemetryCapabilities | None
    if telemetry is _USE_CASE_TELEMETRY:
        resolved_telemetry = case.telemetry
    else:
        resolved_telemetry = cast(TelemetryCapabilities | None, telemetry)
    return _oracle_result(
        evaluate_constraint(
            constraint, prefix_events(case.events, through_seq), telemetry=resolved_telemetry
        ),
        route="deterministic",
    )


def _write_events(events: tuple[Event, ...]) -> tuple[Event, ...]:
    return tuple(
        event
        for event in events
        if event.kind in {"file_write", "file_create", "file_delete"}
        or (event.kind == "tool_end" and event.side_effect in {"write", "delete"})
    )


def _configured_patterns(constraint: Constraint) -> tuple[str, ...]:
    patterns = constraint.oracle.config.get("patterns")
    if not isinstance(patterns, list) or not all(isinstance(pattern, str) for pattern in patterns):
        return ()
    return tuple(pattern for pattern in patterns if pattern)


def _path_matches(path: str, patterns: tuple[str, ...], *, case_sensitive: bool) -> bool:
    # Keep this heuristic intentionally simple and visible; exact path grading
    # belongs to the deterministic oracle.
    from fnmatch import fnmatchcase

    candidate = path if case_sensitive else path.lower()
    return any(
        fnmatchcase(candidate, pattern if case_sensitive else pattern.lower())
        for pattern in patterns
    )


def evaluate_heuristic(case: Case, constraint: Constraint, through_seq: int) -> ArmResult:
    """Run a transparent keyword/path baseline over observed prefix events.

    It alerts only on direct write-path evidence or a direct command keyword,
    and abstains when neither small rule applies. It never treats a read as a
    write and intentionally does not resolve shell indirection.
    """
    events = prefix_events(case.events, through_seq)
    patterns = _configured_patterns(constraint)
    case_sensitive = constraint.oracle.config.get("case_sensitive", True)
    repo_root = constraint.oracle.config.get("repo_root")
    if not isinstance(case_sensitive, bool) or not isinstance(repo_root, (str, type(None))):
        return ArmResult("abstain", "heuristic", "invalid_path_config")
    for event in _write_events(events):
        if event.status != "completed" or event.path is None or event.path_ambiguous:
            continue
        path = normalize_repo_path(event.path, repo_root=repo_root)
        if path and patterns and _path_matches(path, patterns, case_sensitive=case_sensitive):
            return ArmResult("alert", "heuristic", None, score=1.0)

    words = {
        word for word in constraint.verbatim.casefold().replace("-", " ").split() if len(word) > 2
    }
    command_words = {"commit", "push", "install", "curl", "wget", "rm"}
    relevant_words = words & command_words
    for event in events:
        if event.kind not in {"command_start", "command_end", "git_operation"} or not event.command:
            continue
        tokens = set(event.command.casefold().replace("-", " ").split())
        if relevant_words & tokens:
            return ArmResult("alert", "heuristic", None, score=1.0)
    return ArmResult("abstain", "heuristic", "no_direct_keyword_or_path_evidence")


def _is_decisive(result: ArmResult) -> bool:
    return result.oracle_support == "exact" and result.decision in {"alert", "no_alert"}


def evaluate_hybrid(
    case: Case,
    constraint: Constraint,
    through_seq: int,
    *,
    representation: Representation = "normalized_raw",
    cached_semantic: CachedSemanticDecision | None = None,
    telemetry: TelemetrySelection = _USE_CASE_TELEMETRY,
) -> ArmResult:
    """Route exact deterministic decisions around a cached semantic result.

    Non-exact and abstaining deterministic evidence is not promoted to a final
    decision. It requires a cached semantic decision bound to the exact prefix
    state and representation, otherwise the hybrid arm abstains offline.
    """
    deterministic = evaluate_deterministic(case, constraint, through_seq, telemetry=telemetry)
    state_sha256 = evaluator_state_sha256(case, through_seq, representation)
    if _is_decisive(deterministic):
        return ArmResult(
            decision=deterministic.decision,
            route="hybrid_deterministic",
            skip_reason=f"exact_oracle_{deterministic.oracle_outcome}",
            score=deterministic.score,
            oracle_outcome=deterministic.oracle_outcome,
            oracle_support=deterministic.oracle_support,
            state_sha256=state_sha256,
        )
    if representation in {"normalized_raw", "policy_projection_v1"} and requires_v2_representation(
        case
    ):
        return ArmResult(
            "abstain",
            "hybrid_semantic",
            "representation_requires_new_evaluator_protocol",
            oracle_outcome=deterministic.oracle_outcome,
            oracle_support=deterministic.oracle_support,
            state_sha256=state_sha256,
        )
    if cached_semantic is None:
        return ArmResult(
            "abstain",
            "hybrid_semantic",
            "semantic_cache_miss",
            oracle_outcome=deterministic.oracle_outcome,
            oracle_support=deterministic.oracle_support,
            state_sha256=state_sha256,
        )
    if (
        cached_semantic.representation != representation
        or cached_semantic.state_sha256 != state_sha256
    ):
        raise ValueError(
            "cached semantic decision does not match the selected prefix representation"
        )
    return ArmResult(
        decision=cached_semantic.decision,
        route="hybrid_semantic",
        skip_reason=None,
        score=cached_semantic.score,
        oracle_outcome=deterministic.oracle_outcome,
        oracle_support=deterministic.oracle_support,
        state_sha256=state_sha256,
        raw_response_sha256=cached_semantic.raw_response_sha256,
    )


def evaluate_hybrid_prefix_with_jev(
    case: Case,
    constraints: tuple[Constraint, ...],
    through_seq: int,
    *,
    semantic_evaluator: JevEvaluator,
    threshold: float,
    representation: Representation = "normalized_raw",
    telemetry: TelemetrySelection = _USE_CASE_TELEMETRY,
) -> dict[str, ArmResult]:
    """Evaluate one prefix, batching all non-exact hybrid constraints once.

    The evaluator object's network policy controls whether this is cache-only or
    live. An offline miss becomes one abstention per affected constraint rather
    than aborting the cohort. The older ``CachedSemanticDecision`` interface is
    retained by ``evaluate_hybrid`` for documented legacy cache callers.
    """
    if not 0 <= threshold <= 1:
        raise ValueError("semantic threshold must be between zero and one")
    deterministic = {
        constraint.id: evaluate_deterministic(case, constraint, through_seq, telemetry=telemetry)
        for constraint in constraints
    }
    output: dict[str, ArmResult] = {}
    pending = [
        constraint for constraint in constraints if not _is_decisive(deterministic[constraint.id])
    ]
    for constraint in constraints:
        if _is_decisive(deterministic[constraint.id]):
            output[constraint.id] = evaluate_hybrid(
                case, constraint, through_seq, representation=representation, telemetry=telemetry
            )
    if not pending:
        return output
    state_hash = evaluator_state_sha256(case, through_seq, representation)
    if representation not in {
        "normalized_raw",
        "policy_projection_v1",
    } or requires_v2_representation(case):
        for constraint in pending:
            result = deterministic[constraint.id]
            output[constraint.id] = ArmResult(
                "abstain",
                "hybrid_semantic",
                "representation_requires_new_evaluator_protocol",
                oracle_outcome=result.oracle_outcome,
                oracle_support=result.oracle_support,
                state_sha256=state_hash,
            )
        return output
    questions = tuple({"id": constraint.id, "text": constraint.verbatim} for constraint in pending)
    try:
        semantic = semantic_evaluator.evaluate(
            evaluator_state(case, through_seq, representation), questions
        )
        scores = extract_scores(semantic.response, semantic.request)
    except OfflineCacheMiss:
        for constraint in pending:
            result = deterministic[constraint.id]
            output[constraint.id] = ArmResult(
                "abstain",
                "hybrid_semantic",
                "offline_cache_miss",
                oracle_outcome=result.oracle_outcome,
                oracle_support=result.oracle_support,
                state_sha256=state_hash,
            )
        return output
    response_hash = canonical_sha256(semantic.response)
    for constraint in pending:
        result = deterministic[constraint.id]
        score = scores[constraint.id]
        output[constraint.id] = ArmResult(
            "alert" if score >= threshold else "no_alert",
            "hybrid_semantic",
            None,
            score=score,
            oracle_outcome=result.oracle_outcome,
            oracle_support=result.oracle_support,
            state_sha256=state_hash,
            raw_response_sha256=response_hash,
        )
    return output
