"""Small offline CLI for validating, inspecting, and replaying development cases."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from .annotate import collect_annotation, interactive_answer, save_annotations
from .annotations import (
    annotation_set_sha256,
    load_annotation_artifacts,
    overlay_annotation_labels,
    validate_annotation_artifact,
)
from .canonical import canonical_bytes, canonical_sha256
from .codex_jsonl import CodexCaseContext, import_codex_jsonl
from .evaluators import (
    CachedSemanticDecision,
    evaluate_heuristic,
    evaluate_hybrid,
)
from .evidence import normalized_evidence_sha256
from .jev import (
    JevError,
    JevEvaluator,
    OfflineCacheMiss,
    UrllibTransport,
    cache_key_for_request,
    extract_scores,
    load_frozen_config,
)
from .metrics import (
    build_metrics,
    load_dataset_quality,
    quality_excluded_fields,
    write_metrics_csv,
    write_report,
)
from .oracles import evaluate_constraint
from .release import check_case_publication
from .replay import (
    Representation,
    evaluator_state,
    evaluator_state_sha256,
    requires_v2_representation,
)
from .sanitize import sanitize_value
from .schema import (
    AgentProvenance,
    Case,
    Constraint,
    DatasetManifest,
    EvaluationResult,
    EvaluatorConfig,
    InstructionSurface,
    RunCaseIdentity,
    RunManifest,
    validate_run_manifest_bindings,
)

EVENT_SELECTION_VERSION = "all-observed-v1"


def _telemetry_for_oracle(case: Case):
    """Preserve V1 absence semantics while honoring declared new telemetry."""
    if (
        case.source.normalizer_version in {"0.1.0", "synthetic-v1", "synthetic-heldout-v1"}
        and case.source.normalized_evidence_sha256 is None
    ):
        return None
    return case.telemetry


def _deterministic_arm_with_telemetry(case: Case, constraint: Constraint, through_seq: int):
    from .evaluators import ArmResult

    oracle = evaluate_constraint(
        constraint,
        tuple(event for event in case.events if event.seq <= through_seq),
        telemetry=_telemetry_for_oracle(case),
    )
    decision: Literal["alert", "no_alert", "abstain"] = (
        "alert"
        if oracle.outcome == "violated"
        else "no_alert"
        if oracle.outcome == "compliant"
        else "abstain"
    )
    return ArmResult(
        decision=decision,
        route="deterministic",
        skip_reason=None,
        score=1.0 if decision == "alert" else 0.0 if decision == "no_alert" else None,
        oracle_outcome=oracle.outcome,
        oracle_support=oracle.support,
    )


def _case_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.glob("*.json") if p.name != "manifest.json")


def load_case(path: Path) -> Case:
    return Case.model_validate_json(path.read_text(encoding="utf-8"))


def _load_cases(path: Path) -> list[tuple[Path, Case]]:
    """Prevalidate the complete cohort before a command may write a run."""
    paths = _case_paths(path)
    if not paths:
        raise ValueError(f"no case JSON files found under {path}")
    loaded: list[tuple[Path, Case]] = []
    for case_path in paths:
        raw = json.loads(case_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"case must be a JSON object: {case_path}")
        required = ("agent", "task_user_request", "instruction_surfaces", "events", "source")
        missing = [key for key in required if key not in raw]
        if missing:
            raise ValueError(f"case is missing fields {missing}: {case_path}")
        evidence_hash = normalized_evidence_sha256(raw)
        source = raw["source"]
        declared_hash = (
            source.get("normalized_evidence_sha256") or source.get("raw_sha256")
            if isinstance(source, dict)
            else None
        )
        if not isinstance(source, dict) or evidence_hash != declared_hash:
            raise ValueError(f"raw evidence hash mismatch: {case_path}")
        try:
            loaded.append((case_path, Case.model_validate(raw)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid case {case_path}: {exc}") from exc
    if len({case.case_id for _, case in loaded}) != len(loaded):
        raise ValueError("duplicate case IDs")
    return loaded


def _validate_dataset_manifest(
    path: Path, loaded: list[tuple[Path, Case]]
) -> DatasetManifest | None:
    """Validate the dataset manifest whenever a directory is used as a cohort."""
    if not path.is_dir():
        return None
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"dataset manifest is required: {manifest_path}")
    try:
        manifest = DatasetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid dataset manifest {manifest_path}: {exc}") from exc
    ids = [case.case_id for _, case in loaded]
    if list(manifest.case_ids) != ids:
        raise ValueError(
            f"manifest case IDs do not match cases; declared={list(manifest.case_ids)}, actual={ids}"
        )
    declared_hash = manifest.source_provenance[0].raw_sha256
    actual_hash = canonical_sha256(
        [case.source.normalized_evidence_sha256 or case.source.raw_sha256 for _, case in loaded]
    )
    if declared_hash != actual_hash:
        raise ValueError("manifest source hash mismatch")
    return manifest


def _manifest_path(run: Path) -> Path:
    return run.with_suffix(run.suffix + ".manifest.json")


def _row_hash(rows: list[dict[str, object]]) -> str:
    return canonical_sha256(rows)


def _action_eligible(event) -> bool:
    if event.kind == "tool_end":
        return event.side_effect in {"write", "delete", "network"}
    return event.kind in {
        "file_write",
        "file_create",
        "file_delete",
        "command_end",
        "git_operation",
        "test_run",
        "tool_end",
    }


def _validate_audit_row(
    *,
    row: dict[str, object],
    case: Case,
    constraint: Constraint,
    evaluator: EvaluatorConfig,
    representation: Representation,
) -> None:
    """Re-derive fixture-backed audit fields before reporting a stored run."""
    prefix_seq = row["prefix_seq"]
    if not isinstance(prefix_seq, int) or isinstance(prefix_seq, bool):
        raise ValueError("run row prefix sequence is invalid")
    event_by_seq = {event.seq: event for event in case.events}
    event = event_by_seq.get(prefix_seq)
    if event is None or row["action_event_id"] != event.id:
        raise ValueError("run row action event does not match case prefix")
    if row["eligible_for_alert"] is not True:
        raise ValueError("run row alert eligibility does not match all-observed-v1")
    if row["action_event_eligible"] is not _action_eligible(event):
        raise ValueError("run row action-event eligibility does not match case prefix")

    oracle = evaluate_constraint(
        constraint,
        tuple(candidate for candidate in case.events if candidate.seq <= prefix_seq),
        telemetry=_telemetry_for_oracle(case),
    )
    expected_oracle = {
        "oracle_outcome": oracle.outcome,
        "oracle_reason": oracle.reason,
        "oracle_first_event_id": oracle.first_event_id,
    }
    if any(row[field] != value for field, value in expected_oracle.items()):
        raise ValueError("run row oracle evidence does not match case prefix")

    result = EvaluationResult.model_validate(
        {field: row[field] for field in EvaluationResult.model_fields}
    )
    if evaluator.evaluator_type == "rules-v1":
        arm = _deterministic_arm_with_telemetry(case, constraint, prefix_seq)
        if (
            row["route"] != arm.route
            or row["skip_reason"] != arm.skip_reason
            or row["oracle_support"] != arm.oracle_support
            or result.decision != arm.decision
            or result.score != arm.score
            or result.raw_response_sha256 is not None
        ):
            raise ValueError("rule-run row does not match deterministic evaluation")
        return
    if evaluator.evaluator_type == "heuristic-v1":
        arm = evaluate_heuristic(case, constraint, prefix_seq)
        if (
            row["route"] != arm.route
            or row["skip_reason"] != arm.skip_reason
            or row["oracle_support"] is not None
            or result.decision != arm.decision
            or result.score != arm.score
            or result.raw_response_sha256 is not None
        ):
            raise ValueError("heuristic-run row does not match heuristic evaluation")
        return

    if evaluator.evaluator_type == "jev-v2":
        if row["route"] != "semantic":
            raise ValueError("Jev row has an invalid route")
        if requires_v2_representation(case):
            if row["skip_reason"] != "representation_requires_new_evaluator_protocol":
                raise ValueError("Jev row evaluated a V2 case through a frozen representation")
        if row.get("call_id") is not None and row.get("cache_key") is None:
            raise ValueError("Jev row has call_id without cache_key")
        if row.get("from_cache") is True and row.get("call_id") != row.get("cache_key"):
            raise ValueError("cache-hit Jev row call identity mismatch")
        if row["skip_reason"] is not None and result.decision != "abstain":
            raise ValueError("Jev skipped row must abstain")
        if row["skip_reason"] is None:
            if result.score is None:
                raise ValueError("Jev decision row is missing score")
            expected = "alert" if result.score >= (evaluator.threshold or 0.0) else "no_alert"
            if result.decision != expected:
                raise ValueError("Jev score/decision threshold mismatch")
        return

    deterministic = _deterministic_arm_with_telemetry(case, constraint, prefix_seq)
    if row["oracle_support"] != deterministic.oracle_support:
        raise ValueError("hybrid-run oracle support does not match case prefix")
    if deterministic.oracle_support == "exact" and deterministic.decision in {"alert", "no_alert"}:
        arm = evaluate_hybrid(
            case,
            constraint,
            prefix_seq,
            representation=representation,
            telemetry=_telemetry_for_oracle(case),
        )
        if (
            row["route"] != arm.route
            or row["skip_reason"] != arm.skip_reason
            or result.decision != arm.decision
            or result.score != arm.score
            or result.raw_response_sha256 is not None
        ):
            raise ValueError("hybrid deterministic row does not match case prefix")
        return
    if row["route"] != "hybrid_semantic":
        raise ValueError("hybrid semantic row has an invalid route")
    if row["skip_reason"] == "semantic_cache_miss":
        if (
            result.decision != "abstain"
            or result.score is not None
            or result.raw_response_sha256 is not None
        ):
            raise ValueError("hybrid cache-miss row has a semantic decision")
    elif row["skip_reason"] is not None:
        raise ValueError("hybrid semantic row has an invalid skip reason")


def _load_semantic_cache(path: Path | None) -> dict[tuple[str, str, int], CachedSemanticDecision]:
    if path is None:
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid semantic cache: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("semantic cache must be a JSON object keyed by case|constraint|prefix")
    cache: dict[tuple[str, str, int], CachedSemanticDecision] = {}
    for key, value in raw.items():
        parts = key.split("|")
        if len(parts) != 3 or not parts[2].isdigit() or not isinstance(value, dict):
            raise ValueError(f"invalid semantic cache entry: {key}")
        try:
            decision = CachedSemanticDecision(
                state_sha256=value["state_sha256"],
                representation=value["representation"],
                decision=value["decision"],
                score=value.get("score"),
                raw_response_sha256=value.get("raw_response_sha256"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid semantic cache entry: {key}: {exc}") from exc
        cache[(parts[0], parts[1], int(parts[2]))] = decision
    return cache


def validate(path: Path, annotations: Path | None = None) -> int:
    loaded = _load_cases(path)
    ids: list[str] = []
    for case_path, case in loaded:
        ids.append(case.case_id)
        print(
            f"OK {case_path}: {case.case_id} ({len(case.events)} events, {len(case.constraints)} constraints)"
        )
    manifest = _validate_dataset_manifest(path, loaded)
    manifest_path = path / "manifest.json" if path.is_dir() else None
    if manifest is not None and manifest_path is not None:
        print(f"OK {manifest_path}: {manifest.dataset_id} ({len(manifest.case_ids)} cases)")
    if annotations is not None:
        artifacts = load_annotation_artifacts(annotations)
        for _, case in loaded:
            artifact = artifacts.get(case.case_id)
            if artifact is not None:
                validate_annotation_artifact(case, artifact)
        print(f"OK annotations: {len(artifacts)} case(s)")
    return 0


def inspect(path: Path) -> int:
    case = load_case(path)
    print(json.dumps(case.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def sanitize_file(path: Path, output: Path, report_output: Path | None = None) -> int:
    """Sanitize a JSON candidate offline, refusing to overwrite an artifact."""
    if output.exists():
        raise ValueError(f"output already exists; choose a new path: {output}")
    if report_output is not None:
        if report_output == output:
            raise ValueError("sanitized output and report output must be different paths")
        if report_output.exists():
            raise ValueError(f"report output already exists: {report_output}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON candidate: {exc}") from exc
    input_sha256 = canonical_sha256(value)
    from .sanitize import SanitizationReport

    sanitization_report = SanitizationReport()
    sanitized = sanitize_value(value, report=sanitization_report)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.write_bytes(canonical_bytes(sanitized) + b"\n")
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        raise
    print(f"wrote sanitized candidate to {output}")
    if report_output is not None:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_bytes(
            canonical_bytes(
                {
                    "redactions": sanitization_report.redactions,
                    "oversized_values": sanitization_report.oversized_values,
                    "sensitive_fields": sanitization_report.sensitive_fields,
                    "findings": sanitization_report.findings,
                    "publication_allowed": sanitization_report.publication_allowed,
                    "sanitizer_version": "sanitize-v1",
                    "input_sha256": input_sha256,
                    "output_sha256": canonical_sha256(sanitized),
                }
            )
            + b"\n"
        )
        print(f"wrote sanitization report to {report_output}")
    return 0


def release_check(path: Path) -> int:
    """Fail closed for publication checks and print issue metadata only."""
    if path.is_file() and not path.name.endswith(".manifest.json"):
        adjacent = _manifest_path(path)
        if adjacent.is_file():
            return release_check(adjacent)
    if path.is_dir() and (path / "metrics.json").is_file():
        try:
            report_value = json.loads((path / "metrics.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid report artifact: {exc}") from exc
        primary = report_value.get("primary")
        if not isinstance(primary, dict):
            primary = {}

        def _operational_count(name: str) -> int | float:
            value = primary.get(name)
            if value is None:
                return 0
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"invalid report metric {name}: expected a number or null")
            return value

        if (
            _operational_count("provider_call_count") > 0
            or _operational_count("cache_hit_count") > 0
            or _operational_count("cache_miss_count") > 0
            or report_value.get("provider_result") is True
        ):
            print(
                "FAIL provider-result publication permission is unresolved; keep this artifact private"
            )
            return 2
        print(f"OK report release checks passed for {path}")
        return 0
    if path.is_file() and path.name.endswith(".manifest.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid run manifest: {exc}") from exc
        if manifest.get("run_kind") in {"jev-v2", "hybrid-v1"} or manifest.get("provider_result"):
            print(
                "FAIL provider-result publication permission is unresolved; keep this artifact private"
            )
            return 2
        print(f"OK run release checks passed for {path}")
        return 0
    if path.is_dir():
        cases = _load_cases(path)
        _validate_dataset_manifest(path, cases)
        checks = [(case_path, check_case_publication(case)) for case_path, case in cases]
    else:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            case = Case.model_validate(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid case candidate: {exc}") from exc
        checks = [(path, check_case_publication(case))]
    issues = [(case_path, issue) for case_path, result in checks for issue in result.issues]
    if issues:
        for case_path, issue in issues:
            suffix = f" [{issue.path}]" if issue.path else ""
            print(f"FAIL {case_path}: {issue.code}{suffix}: {issue.message}")
        return 2
    print(f"OK publication checks passed for {len(checks)} case(s)")
    return 0


def annotate_case(
    path: Path,
    constraint_id: str,
    output: Path,
    overwrite: bool,
    annotator_id: str | None = None,
) -> int:
    """Collect one human label into a separate artifact without changing the case."""
    case = load_case(path)

    def navigable_answer(prompt):
        if prompt.prefix_seq == prompt.prefix_events[-1]["seq"]:
            index = 0
            while True:
                event = prompt.prefix_events[index]
                print(f"Prefix {event['seq']}: {json.dumps(event, ensure_ascii=False)}")
                command = input("Navigation [n=next,p=previous,f=finish]: ").strip().lower()
                if command == "n":
                    index = min(index + 1, len(prompt.prefix_events) - 1)
                elif command == "p":
                    index = max(index - 1, 0)
                elif command == "f":
                    break
            return interactive_answer(prompt)
        return {"outcome": "ungradeable", "annotation_method": "human"}

    label = collect_annotation(case, constraint_id, navigable_answer, overwrite=overwrite)
    save_annotations(output, case, {constraint_id: label}, overwrite=overwrite)
    if annotator_id is not None:
        raw = json.loads(output.read_text(encoding="utf-8"))
        raw["annotator_id"] = annotator_id
        output.write_bytes(canonical_bytes(raw) + b"\n")
    print(f"wrote annotation artifact to {output}")
    return 0


def import_trace(
    source: Path,
    context_path: Path,
    output: Path,
    *,
    max_line_bytes: int,
    max_records: int,
) -> int:
    """Import a bounded Codex JSONL trace using caller-supplied runtime context."""
    if output.exists():
        raise ValueError(f"output already exists; choose a new path: {output}")
    try:
        context_raw = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read context JSON: {exc}") from exc
    if not isinstance(context_raw, dict):
        raise ValueError("context JSON must be an object")
    allowed = {
        "case_id",
        "agent",
        "task_user_request",
        "instruction_surfaces",
        "constraints",
        "origin_uri",
        "license",
        "redistribution_allowed",
        "starting_repo_tree",
        "filesystem_case_sensitive",
    }
    unknown = set(context_raw) - allowed
    if unknown:
        raise ValueError(f"context contains unsupported fields: {sorted(unknown)}")
    try:
        context = CodexCaseContext(
            case_id=context_raw["case_id"],
            agent=AgentProvenance.model_validate(context_raw["agent"]),
            task_user_request=context_raw["task_user_request"],
            instruction_surfaces=tuple(
                InstructionSurface.model_validate(item)
                for item in context_raw["instruction_surfaces"]
            ),
            constraints=tuple(
                Constraint.model_validate(item) for item in context_raw["constraints"]
            ),
            origin_uri=context_raw.get("origin_uri"),
            license=context_raw.get("license"),
            redistribution_allowed=context_raw.get("redistribution_allowed"),
            starting_repo_tree=tuple(context_raw.get("starting_repo_tree", ())),
            filesystem_case_sensitive=context_raw.get("filesystem_case_sensitive"),
        )
        case = import_codex_jsonl(
            source,
            context,
            max_line_bytes=max_line_bytes,
            max_records=max_records,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid import context or trace: {exc}") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.write_bytes(canonical_bytes(case) + b"\n")
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        raise
    print(f"wrote imported case to {output}")
    return 0


def plan_run(
    path: Path,
    evaluator: str,
    cache: Path | None,
    representation: Representation = "normalized_raw",
    jev_config: Path | None = None,
) -> int:
    """Print a network-free estimate for an evaluation run."""
    cases = _load_cases(path)
    _validate_dataset_manifest(path, cases)
    if evaluator not in {"rules-v1", "jev-v1", "jev-v2", "hybrid-v1"}:
        raise ValueError(
            "supported planning evaluators are rules-v1, jev-v1, jev-v2, and hybrid-v1"
        )
    units = sum(len(case.constraints) for _, case in cases)
    prefixes = sum(len(case.events) for _, case in cases)
    eligible_prefixes = prefixes
    is_jev = evaluator in {"jev-v1", "jev-v2", "hybrid-v1"}
    # Jev evaluates all typed questions over one state in a single request.
    # Each prefix is therefore one possible API call, regardless of the
    # number of constraints carried by that case.
    potential_calls = prefixes if is_jev else 0
    cache_hits = 0
    cache_supported = is_jev
    if cache_supported and cache is not None and cache.exists():
        if cache.is_dir():
            cache_keys = {p.stem for p in cache.glob("*.json") if p.is_file()}
        else:
            try:
                cached = json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid cache index: {exc}") from exc
            if isinstance(cached, dict):
                cache_keys = set(cached)
            elif isinstance(cached, list) and all(isinstance(item, str) for item in cached):
                cache_keys = set(cached)
            else:
                raise ValueError("cache index must be a JSON object or list of string keys")
        frozen_hash = None
        if jev_config is not None:
            frozen_hash = str(load_frozen_config(jev_config)["evaluator_spec_sha256"])
        for _, case in cases:
            for event in case.events:
                state = evaluator_state(case, event.seq, representation)
                constraints = tuple({"id": c.id, "text": c.verbatim} for c in case.constraints)
                key = cache_key_for_request(state, constraints, evaluator_spec_hash=frozen_hash)
                cache_hits += key in cache_keys
    max_input_tokens_per_request = 64_000 if is_jev else 0
    input_price_usd_per_million_tokens = 0.042 if is_jev else 0.0
    max_input_tokens = potential_calls * max_input_tokens_per_request
    plan = {
        "plan_version": "plan-v1",
        "evaluator": evaluator,
        "network_calls": 0,
        "dataset_cases": len(cases),
        "constraints": units,
        "prefixes": prefixes,
        "eligible_prefixes": eligible_prefixes,
        "potential_calls": potential_calls,
        "cache_supported": cache_supported,
        "cache_hits": cache_hits,
        "live_calls_after_cache": max(0, potential_calls - cache_hits),
        "input_price_usd_per_million_tokens": input_price_usd_per_million_tokens,
        "maximum_input_tokens": max_input_tokens,
        "maximum_cost_usd": round(
            max_input_tokens * input_price_usd_per_million_tokens / 1_000_000, 9
        ),
        "cost_estimate_note": (
            "The API bills input tokens only. This is a documented 64k-token "
            "per-request upper bound, not a tokenizer-derived prediction."
            if is_jev
            else None
        ),
        "authorization_required": False,
        "note": "planning is offline and does not authorize or perform provider calls",
    }
    print(json.dumps(plan, sort_keys=True))
    return 0


def _typed_run_manifest(
    *,
    run_kind: str,
    evaluator: EvaluatorConfig,
    cases: list[tuple[Path, Case]],
    rows: list[dict[str, object]],
    network_allowed: bool,
    provider_call_count: int = 0,
    cache_hit_count: int = 0,
    cache_miss_count: int = 0,
    evaluator_spec_sha256: str | None = None,
) -> dict[str, object]:
    dataset_id = None
    dataset_manifest_sha256 = None
    if cases and cases[0][0].parent.is_dir() and (cases[0][0].parent / "manifest.json").is_file():
        manifest_path = cases[0][0].parent / "manifest.json"
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        dataset_id = raw_manifest.get("dataset_id")
        dataset_manifest_sha256 = canonical_sha256(raw_manifest)
    typed = RunManifest(
        run_id=str(uuid.uuid4()),
        run_kind=run_kind,
        created_at_utc=datetime.now(UTC).isoformat(),
        dataset_id=dataset_id,
        dataset_manifest_sha256=dataset_manifest_sha256,
        evaluator=evaluator,
        evaluator_sha256=canonical_sha256(evaluator),
        evaluator_spec_sha256=evaluator_spec_sha256,
        representation=evaluator.projection_version,
        event_selection_version=evaluator.event_selection_version,
        python_version=sys.version.split()[0],
        network_allowed=network_allowed,
        provider_call_count=provider_call_count,
        cache_hit_count=cache_hit_count,
        cache_miss_count=cache_miss_count,
        cases=tuple(
            RunCaseIdentity(
                case_id=case.case_id,
                case_sha256=canonical_sha256(case),
                evidence_sha256=case.source.normalized_evidence_sha256 or case.source.raw_sha256,
            )
            for _, case in cases
        ),
        row_count=len(rows),
        rows_sha256=_row_hash(rows),
    )
    return typed.model_dump(mode="json")


def eval_rules(
    path: Path,
    output: Path,
    evaluator_name: str = "rules-v1",
    semantic_cache: Path | None = None,
    representation: Representation = "normalized_raw",
    *,
    jev_config: Path | None = None,
    cache_dir: Path | None = None,
    live: bool = False,
    force: bool = False,
) -> int:
    if evaluator_name == "jev-v2":
        return eval_jev(
            path,
            output,
            representation=representation,
            jev_config=jev_config,
            cache_dir=cache_dir,
            live=live,
            force=force,
        )
    if evaluator_name not in {"rules-v1", "heuristic-v1", "hybrid-v1"}:
        raise ValueError("only rules-v1, heuristic-v1, and hybrid-v1 are available offline")
    if representation not in {"normalized_raw", "policy_projection_v1"}:
        raise ValueError(f"unsupported replay representation: {representation}")
    config = EvaluatorConfig(
        evaluator_type=evaluator_name,
        implementation_version="0.1.0",
        question_spec_version="none",
        projection_version=representation,
        event_selection_version=EVENT_SELECTION_VERSION,
    )
    cases = _load_cases(path)
    _validate_dataset_manifest(path, cases)
    semantic_decisions = _load_semantic_cache(semantic_cache)
    manifest_output = _manifest_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.with_suffix(output.suffix + ".lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(f"output is already being written: {output}") from exc
    os.close(lock_fd)
    if output.exists() or manifest_output.exists():
        lock.unlink(missing_ok=True)
        raise ValueError(f"output already exists; choose a new run path: {output}")
    rows: list[dict[str, object]] = []
    for _, case in cases:
        for event in case.events:
            prefix = tuple(e for e in case.events if e.seq <= event.seq)
            for constraint in case.constraints:
                decision = evaluate_constraint(
                    constraint, prefix, telemetry=_telemetry_for_oracle(case)
                )
                if evaluator_name == "rules-v1":
                    arm = _deterministic_arm_with_telemetry(case, constraint, event.seq)
                elif evaluator_name == "heuristic-v1":
                    arm = evaluate_heuristic(case, constraint, event.seq)
                else:
                    arm = evaluate_hybrid(
                        case,
                        constraint,
                        event.seq,
                        representation=representation,
                        telemetry=_telemetry_for_oracle(case),
                        cached_semantic=semantic_decisions.get(
                            (case.case_id, constraint.id, event.seq)
                        ),
                    )
                result = EvaluationResult(
                    case_id=case.case_id,
                    constraint_id=constraint.id,
                    prefix_seq=event.seq,
                    evaluator=config,
                    decision=arm.decision,
                    score=arm.score,
                    state_sha256=evaluator_state_sha256(case, event.seq, representation),
                    raw_response_sha256=arm.raw_response_sha256,
                )
                record: dict[str, object] = result.model_dump(mode="json") | {
                    "action_event_id": event.id,
                    "eligible_for_alert": True,
                    "action_event_eligible": _action_eligible(event),
                    "oracle_outcome": decision.outcome,
                    "oracle_reason": decision.reason,
                    "oracle_first_event_id": decision.first_event_id,
                    "route": arm.route,
                    "skip_reason": arm.skip_reason,
                    "oracle_support": arm.oracle_support,
                    # Deterministic rows carry no semantic usage; keep the
                    # operational schema numeric for metrics compatibility.
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "latency_seconds": 0.0,
                    "cost_usd": 0.0,
                }
                rows.append(record)
    manifest = _typed_run_manifest(
        run_kind=evaluator_name,
        evaluator=config,
        cases=cases,
        rows=rows,
        network_allowed=False,
    )
    descriptor, temporary_name = tempfile.mkstemp(prefix=".run-", suffix=".tmp", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    manifest_temp = temporary.with_name(temporary.name + ".manifest")
    try:
        temporary.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
        )
        manifest_temp.write_bytes(canonical_bytes(manifest) + b"\n")
        os.replace(temporary, output)
        os.replace(manifest_temp, manifest_output)
    except Exception:
        temporary.unlink(missing_ok=True)
        manifest_temp.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        manifest_output.unlink(missing_ok=True)
        raise
    finally:
        lock.unlink(missing_ok=True)
    print(f"wrote {len(rows)} results to {output}")
    return 0


def eval_jev(
    path: Path,
    output: Path,
    *,
    representation: Representation = "normalized_raw",
    jev_config: Path | None = None,
    cache_dir: Path | None = None,
    live: bool = False,
    force: bool = False,
    case_ids: set[str] | None = None,
) -> int:
    """Run the canonical Jev adapter, cache-only unless ``live`` is explicit."""
    config_path = jev_config or Path("configs/evaluators/jev-contract-monitor-v1.json")
    frozen = load_frozen_config(config_path)
    threshold = float(frozen["threshold"])
    cases = _load_cases(path)
    dataset_manifest = _validate_dataset_manifest(path, cases)
    if case_ids is not None:
        cases = [(case_path, case) for case_path, case in cases if case.case_id in case_ids]
        if not cases:
            raise ValueError("case_ids selected no cases")
        if dataset_manifest is not None and not set(case_ids).issubset(
            set(dataset_manifest.case_ids)
        ):
            raise ValueError("case_ids contain IDs outside the dataset manifest")
    semantic = JevEvaluator(
        cache_dir=cache_dir or Path(".jev-cache/jev-contract-monitor-v1"),
        transport=UrllibTransport() if live else None,
        allow_network=live,
    )
    config = EvaluatorConfig(
        evaluator_type="jev-v2",
        implementation_version="jev-v2",
        model_id=str(frozen["model"]),
        question_spec_version=str(frozen["question_spec_version"]),
        projection_version=representation,
        event_selection_version=str(frozen["event_selection_version"]),
        threshold=threshold,
    )
    rows: list[dict[str, object]] = []
    for _, case in cases:
        for event in case.events:
            prefix = tuple(candidate for candidate in case.events if candidate.seq <= event.seq)
            base = {
                "case_id": case.case_id,
                "prefix_seq": event.seq,
                "action_event_id": event.id,
                "eligible_for_alert": True,
                "action_event_eligible": _action_eligible(event),
            }
            constraints = tuple({"id": c.id, "text": c.verbatim} for c in case.constraints)
            operational: dict[str, object] = {
                "call_id": None,
                "cache_key": None,
                "from_cache": False,
                "provider_call_made": False,
                "provider_call_made_this_run": False,
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_seconds": 0.0,
                "cost_usd": 0.0,
                "error_code": None,
                "model_requested": config.model_id,
                "model_resolved": None,
            }
            result_by_constraint: dict[
                str,
                tuple[
                    Literal["alert", "no_alert", "abstain"], float | None, str | None, str | None
                ],
            ] = {}
            state_hash = evaluator_state_sha256(case, event.seq, representation)
            request_cache_key = cache_key_for_request(
                evaluator_state(case, event.seq, representation),
                constraints,
                evaluator_spec_hash=str(frozen["evaluator_spec_sha256"]),
            )
            if representation not in {
                "normalized_raw",
                "policy_projection_v1",
            } or requires_v2_representation(case):
                for constraint in case.constraints:
                    result_by_constraint[constraint.id] = (
                        "abstain",
                        None,
                        "representation_requires_new_evaluator_protocol",
                        None,
                    )
            else:
                try:
                    evaluated = semantic.evaluate(
                        evaluator_state(case, event.seq, representation), constraints, force=force
                    )
                    scores = extract_scores(evaluated.response, evaluated.request)
                    usage = evaluated.response.get("usage", {})
                    operational.update(
                        {
                            "call_id": evaluated.call_id,
                            "cache_key": evaluated.cache_key,
                            "from_cache": evaluated.from_cache,
                            "provider_call_made_this_run": evaluated.provider_call_made_this_run,
                            "provider_call_made": evaluated.provider_call_made_this_run,
                            "input_tokens": usage.get("input_tokens"),
                            "output_tokens": usage.get("output_tokens"),
                            "latency_seconds": evaluated.metadata.get("latency_seconds"),
                            "model_resolved": evaluated.response.get("model"),
                        }
                    )
                    response_hash = canonical_sha256(evaluated.response)
                    for constraint in case.constraints:
                        score = scores[constraint.id]
                        result_by_constraint[constraint.id] = (
                            "alert" if score >= threshold else "no_alert",
                            score,
                            None,
                            response_hash,
                        )
                except OfflineCacheMiss:
                    operational["error_code"] = "offline_cache_miss"
                    operational["cache_key"] = request_cache_key
                    operational["call_id"] = request_cache_key
                    for constraint in case.constraints:
                        result_by_constraint[constraint.id] = (
                            "abstain",
                            None,
                            "offline_cache_miss",
                            None,
                        )
                except JevError:
                    operational["error_code"] = "jev_evaluation_failed"
                    operational["cache_key"] = request_cache_key
                    operational["call_id"] = request_cache_key
                    for constraint in case.constraints:
                        result_by_constraint[constraint.id] = (
                            "abstain",
                            None,
                            "jev_evaluation_failed",
                            None,
                        )
            for constraint in case.constraints:
                row_decision, row_score, row_skip_reason, row_response_hash = cast(
                    tuple[
                        Literal["alert", "no_alert", "abstain"],
                        float | None,
                        str | None,
                        str | None,
                    ],
                    result_by_constraint[constraint.id],
                )
                oracle = evaluate_constraint(
                    constraint, prefix, telemetry=_telemetry_for_oracle(case)
                )
                row = EvaluationResult(
                    case_id=case.case_id,
                    constraint_id=constraint.id,
                    prefix_seq=event.seq,
                    evaluator=config,
                    decision=row_decision,
                    score=row_score,
                    state_sha256=state_hash,
                    raw_response_sha256=row_response_hash,
                ).model_dump(mode="json")
                row.update(
                    base,
                    oracle_outcome=oracle.outcome,
                    oracle_reason=oracle.reason,
                    oracle_first_event_id=oracle.first_event_id,
                    route="semantic",
                    skip_reason=row_skip_reason,
                    oracle_support=oracle.support,
                )
                row.update(operational)
                rows.append(row)
    manifest = _typed_run_manifest(
        run_kind="jev-v2",
        evaluator=config,
        cases=cases,
        rows=rows,
        network_allowed=live,
        provider_call_count=len(
            {row.get("call_id") for row in rows if row.get("provider_call_made") is True}
        ),
        cache_hit_count=len({row.get("call_id") for row in rows if row.get("from_cache") is True}),
        cache_miss_count=len(
            {row.get("call_id") for row in rows if row.get("error_code") == "offline_cache_miss"}
        ),
        evaluator_spec_sha256=str(frozen["evaluator_spec_sha256"]),
    )
    _write_run_artifacts(output, rows, manifest)
    print(f"wrote {len(rows)} results to {output}")
    return 0


def _write_run_artifacts(
    output: Path, rows: list[dict[str, object]], manifest: dict[str, object]
) -> None:
    manifest_output = _manifest_path(output)
    if output.exists() or manifest_output.exists():
        raise ValueError(f"run output already exists; choose a new path: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    manifest_temp = manifest_output.with_name(f".{manifest_output.name}.tmp")
    try:
        temporary.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
        )
        manifest_temp.write_bytes(canonical_bytes(manifest) + b"\n")
        os.replace(temporary, output)
        os.replace(manifest_temp, manifest_output)
    except Exception:
        temporary.unlink(missing_ok=True)
        manifest_temp.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        manifest_output.unlink(missing_ok=True)
        raise


def report_from_cases(
    run: Path,
    cases_path: Path,
    output_dir: Path,
    annotations: Path | None = None,
    dataset_quality: Path | None = None,
) -> int:
    if not run.is_file():
        raise ValueError(f"run output does not exist: {run}")
    manifest_path = _manifest_path(run)
    if not manifest_path.is_file():
        raise ValueError(f"run manifest does not exist: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = [
            json.loads(line)
            for line in run.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"malformed run artifacts: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("run manifest must be a JSON object")
    cases = _load_cases(cases_path)
    dataset_manifest = _validate_dataset_manifest(cases_path, cases)
    # A smoke run may intentionally select a manifest subset.  Resolve that
    # selection against the validated parent cohort before binding rows.
    manifest_case_entries = manifest.get("cases")
    if dataset_manifest is not None and isinstance(manifest_case_entries, list):
        selected_ids = {
            entry.get("case_id")
            for entry in manifest_case_entries
            if isinstance(entry, dict) and isinstance(entry.get("case_id"), str)
        }
        parent_ids = set(dataset_manifest.case_ids)
        if not selected_ids or not selected_ids.issubset(parent_ids):
            raise ValueError("run manifest case selection is outside the parent dataset")
        cases = [(case_path, case) for case_path, case in cases if case.case_id in selected_ids]
    quality: dict[str, object] = {}
    if dataset_quality is not None:
        try:
            quality = load_dataset_quality(dataset_quality)
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid dataset quality file: {exc}") from exc
        if quality.get("dataset_id") != (dataset_manifest.dataset_id if dataset_manifest else None):
            raise ValueError("dataset quality dataset_id does not match case manifest")
    if manifest.get("schema_version") != "1.0" or manifest.get("run_kind") not in {
        "rules-v1",
        "heuristic-v1",
        "hybrid-v1",
        "jev-v2",
    }:
        raise ValueError("unsupported or malformed run manifest")
    if not isinstance(manifest.get("cases"), list) or not isinstance(
        manifest.get("row_count"), int
    ):
        raise ValueError("run manifest has malformed cases or row_count")
    try:
        typed_manifest = RunManifest.model_validate(manifest)
        expected_identities = tuple(
            RunCaseIdentity(
                case_id=case.case_id,
                case_sha256=canonical_sha256(case),
                evidence_sha256=case.source.normalized_evidence_sha256 or case.source.raw_sha256,
            )
            for _, case in cases
        )
        validate_run_manifest_bindings(
            typed_manifest,
            row_count=len(rows),
            rows_sha256=_row_hash(rows),
            case_identities=expected_identities,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"run manifest does not match rows or current case fixtures: {exc}"
        ) from exc
    try:
        evaluator = EvaluatorConfig.model_validate(manifest.get("evaluator"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid run evaluator: {exc}") from exc
    if evaluator.evaluator_type != manifest.get("run_kind") or manifest.get(
        "evaluator_sha256"
    ) != canonical_sha256(evaluator):
        raise ValueError("run manifest evaluator hash mismatch")
    if evaluator.event_selection_version != EVENT_SELECTION_VERSION:
        raise ValueError("unsupported event-selection policy in run manifest")
    if evaluator.projection_version not in {"normalized_raw", "policy_projection_v1"}:
        raise ValueError("unsupported replay representation in run manifest")
    report_representation = cast(Representation, evaluator.projection_version)
    core_fields = set(EvaluationResult.model_fields)
    audit_fields = {
        "action_event_id",
        "eligible_for_alert",
        "action_event_eligible",
        "oracle_outcome",
        "oracle_reason",
        "oracle_first_event_id",
        "route",
        "skip_reason",
        "oracle_support",
    }
    required_fields = core_fields | audit_fields
    operational_fields = {
        "call_id",
        "cache_key",
        "from_cache",
        "provider_call_made_this_run",
        "input_tokens",
        "output_tokens",
        "latency_seconds",
        "cost_usd",
        "error_code",
        "model_requested",
        "model_resolved",
    }
    if manifest.get("run_kind") == "jev-v2":
        required_fields |= operational_fields
    for row in rows:
        if not isinstance(row, dict) or set(row) != required_fields:
            raise ValueError("run row has missing or unknown fields")
        try:
            result = EvaluationResult.model_validate({key: row[key] for key in core_fields})
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid run result row: {exc}") from exc
        if result.evaluator != evaluator:
            raise ValueError("run row evaluator differs from manifest")
    artifacts = load_annotation_artifacts(annotations) if annotations is not None else {}
    unknown_artifacts = set(artifacts) - {case.case_id for _, case in cases}
    if unknown_artifacts:
        raise ValueError(
            f"annotations reference cases outside the report cohort: {sorted(unknown_artifacts)}"
        )
    if dataset_manifest and dataset_manifest.dataset_id == "synthetic-semantic-development-v1":
        if any(artifact.legacy_unbound for artifact in artifacts.values()):
            raise ValueError("semantic-development reporting requires bound annotation artifacts")
    labels: dict[tuple[str, str], dict[str, object]] = {}
    metadata: dict[tuple[str, str], dict[str, object]] = {}
    expected_units = {
        (case.case_id, constraint.id) for _, case in cases for constraint in case.constraints
    }
    row_units = {(row.get("case_id"), row.get("constraint_id")) for row in rows}
    if row_units != expected_units:
        raise ValueError("run rows have missing or extra case-constraint units")
    expected_row_keys = {
        (case.case_id, constraint.id, event.seq)
        for _, case in cases
        for constraint in case.constraints
        for event in case.events
    }
    row_keys = {
        (row.get("case_id"), row.get("constraint_id"), row.get("prefix_seq")) for row in rows
    }
    if row_keys != expected_row_keys or len(row_keys) != len(rows):
        raise ValueError("run rows are missing, duplicated, or stale")
    for _, case in cases:
        constraints = {constraint.id: constraint for constraint in case.constraints}
        for row in (item for item in rows if item["case_id"] == case.case_id):
            if row["state_sha256"] != evaluator_state_sha256(
                case, int(row["prefix_seq"]), report_representation
            ):
                raise ValueError("run row state hash does not match current prefix")
            _validate_audit_row(
                row=row,
                case=case,
                constraint=constraints[row["constraint_id"]],
                evaluator=evaluator,
                representation=report_representation,
            )
        by_event = {event.id: event.seq for event in case.events}
        effective_case_labels = dict(case.labels)
        artifact = artifacts.get(case.case_id)
        if artifact is not None:
            effective_case_labels = overlay_annotation_labels(case, artifact)
        for constraint in case.constraints:
            label = effective_case_labels.get(constraint.id)
            if label is None:
                continue
            dumped = label.model_dump(mode="json")
            for field in quality_excluded_fields(quality, case.case_id):
                dumped.pop(field, None)
                dumped.pop(field.replace("_event", "_seq"), None)
            for source, target in (
                ("first_clear_violation_event", "first_clear_violation_seq"),
                ("first_effect_event", "first_effect_seq"),
                ("earliest_observable_risk_event", "earliest_observable_risk_seq"),
            ):
                if dumped.get(source) in by_event:
                    dumped[target] = by_event[dumped[source]]
            labels[(case.case_id, constraint.id)] = dumped
            metadata[(case.case_id, constraint.id)] = {
                "category": constraint.category,
                "oracle_kind": constraint.oracle.kind,
            }
    metrics = build_metrics(rows, labels, metadata)
    unresolved = 0
    for _, case in cases:
        effective = dict(case.labels)
        if case.case_id in artifacts:
            effective = overlay_annotation_labels(case, artifacts[case.case_id])
        unresolved += sum(
            1
            for constraint in case.constraints
            if constraint.id not in effective
            or effective[constraint.id].annotation_method == "pending_human_review"
        )
    metrics["annotation_provenance"] = {
        "artifact_count": len(artifacts),
        "annotation_set_sha256": annotation_set_sha256(artifacts) if artifacts else None,
        "labels_supplied_by_overlay": sum(len(artifact.labels) for artifact in artifacts.values()),
        "unresolved_human_or_pending_constraints": unresolved,
    }
    metrics["dataset_quality_provenance"] = {
        "path": str(dataset_quality) if dataset_quality is not None else None,
        "sha256": canonical_sha256(quality) if quality else None,
        "excluded_fields": quality.get("issues", {}) if isinstance(quality, dict) else {},
    }
    write_report(metrics, output_dir)
    write_metrics_csv(metrics, output_dir / "metrics.csv")
    print(f"wrote report to {output_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="contract-eval")
    sub = parser.add_subparsers(dest="command", required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("path", type=Path)
    validate_parser.add_argument("--annotations", type=Path)
    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("path", type=Path)
    sanitize_parser = sub.add_parser("sanitize")
    sanitize_parser.add_argument("path", type=Path)
    sanitize_parser.add_argument("--out", type=Path, required=True)
    sanitize_parser.add_argument("--report", type=Path)
    release_parser = sub.add_parser("release-check")
    release_parser.add_argument("path", type=Path)
    annotate_parser = sub.add_parser("annotate")
    annotate_parser.add_argument("path", type=Path)
    annotate_parser.add_argument("--constraint", required=True)
    annotate_parser.add_argument("--out", type=Path, required=True)
    annotate_parser.add_argument("--overwrite", action="store_true")
    annotate_parser.add_argument("--annotator-id")
    import_parser = sub.add_parser("import")
    import_parser.add_argument("source", type=Path)
    import_parser.add_argument("--context", type=Path, required=True)
    import_parser.add_argument("--out", type=Path, required=True)
    import_parser.add_argument("--max-line-bytes", type=int, default=1_048_576)
    import_parser.add_argument("--max-records", type=int, default=100_000)
    plan_parser = sub.add_parser("plan-run")
    plan_parser.add_argument("path", type=Path)
    plan_parser.add_argument("--evaluator", default="rules-v1")
    plan_parser.add_argument("--cache", type=Path)
    plan_parser.add_argument(
        "--representation",
        choices=("normalized_raw", "policy_projection_v1"),
        default="normalized_raw",
    )
    plan_parser.add_argument("--jev-config", type=Path)
    eval_parser = sub.add_parser("eval")
    eval_parser.add_argument("path", type=Path)
    eval_parser.add_argument(
        "--evaluator",
        choices=("rules-v1", "heuristic-v1", "jev-v2", "hybrid-v1"),
        default="rules-v1",
    )
    eval_parser.add_argument("--semantic-cache", type=Path)
    eval_parser.add_argument("--jev-config", type=Path)
    eval_parser.add_argument("--cache-dir", type=Path)
    eval_parser.add_argument("--live", action="store_true")
    eval_parser.add_argument("--force", action="store_true")
    eval_parser.add_argument(
        "--representation",
        choices=("normalized_raw", "policy_projection_v1"),
        default="normalized_raw",
    )
    eval_parser.add_argument("--out", type=Path, default=Path("results/runs/rules-v1.jsonl"))
    report_parser = sub.add_parser("report")
    report_parser.add_argument("--run", type=Path, required=True)
    report_parser.add_argument("--cases", type=Path, required=True)
    report_parser.add_argument("--out-dir", type=Path, required=True)
    report_parser.add_argument("--annotations", type=Path)
    report_parser.add_argument("--dataset-quality", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            return validate(args.path, args.annotations)
        if args.command == "inspect":
            return inspect(args.path)
        if args.command == "sanitize":
            return sanitize_file(args.path, args.out, args.report)
        if args.command == "release-check":
            return release_check(args.path)
        if args.command == "annotate":
            return annotate_case(
                args.path, args.constraint, args.out, args.overwrite, args.annotator_id
            )
        if args.command == "import":
            if args.max_line_bytes < 1 or args.max_records < 1:
                raise ValueError("import bounds must be positive")
            return import_trace(
                args.source,
                args.context,
                args.out,
                max_line_bytes=args.max_line_bytes,
                max_records=args.max_records,
            )
        if args.command == "plan-run":
            return plan_run(
                args.path, args.evaluator, args.cache, args.representation, args.jev_config
            )
        if args.command == "eval":
            return eval_rules(
                args.path,
                args.out,
                args.evaluator,
                args.semantic_cache,
                args.representation,
                jev_config=args.jev_config,
                cache_dir=args.cache_dir,
                live=args.live,
                force=args.force,
            )
        if args.command == "report":
            return report_from_cases(
                args.run, args.cases, args.out_dir, args.annotations, args.dataset_quality
            )
    except (OSError, ValueError, TypeError) as exc:
        print(f"error: {exc}")
        return 2
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
