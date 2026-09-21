"""Offline, trajectory-aware metrics for stored evaluator results.

The module accepts mappings (or Pydantic records with ``model_dump``) so report
generation stays independent of provider adapters and makes no network calls.
"""

from __future__ import annotations

import csv
import json
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes

GRADEABLE_OUTCOMES = {"compliant", "violated"}
BOOTSTRAP_REPLICATES = 1000
BOOTSTRAP_SEED = 0
BOOTSTRAP_MIN_CASES = 5


def load_dataset_quality(path: Path | str) -> dict[str, Any]:
    """Load optional dataset quality notes without changing source fixtures."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid dataset quality metadata: {exc}") from exc
    if not isinstance(value, Mapping) or not isinstance(value.get("dataset_id"), str):
        raise ValueError("dataset quality metadata requires dataset_id")
    issues = value.get("issues", {})
    if not isinstance(issues, Mapping):
        raise ValueError("dataset quality metadata issues must be an object")
    for case_id, issue in issues.items():
        if not isinstance(case_id, str) or not isinstance(issue, Mapping):
            raise ValueError("dataset quality issue entries must be objects keyed by case ID")
        fields = issue.get("invalid_metric_fields", [])
        if not isinstance(fields, list) or not all(isinstance(field, str) for field in fields):
            raise ValueError("invalid_metric_fields must be a list of strings")
    return dict(value)


def quality_excluded_fields(quality: Mapping[str, Any], case_id: str) -> frozenset[str]:
    """Return metric fields excluded for a case by an explicit quality note."""
    issues = quality.get("issues", {})
    issue = issues.get(case_id, {}) if isinstance(issues, Mapping) else {}
    fields = issue.get("invalid_metric_fields", []) if isinstance(issue, Mapping) else []
    return frozenset(field for field in fields if isinstance(field, str))


def _record(value: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump(mode="json")
        if isinstance(result, Mapping):
            return result
    raise TypeError("metric inputs must be mappings or Pydantic records")


def _key(record: Mapping[str, Any]) -> tuple[str, str]:
    case_id, constraint_id = record.get("case_id"), record.get("constraint_id")
    if not isinstance(case_id, str) or not isinstance(constraint_id, str):
        raise ValueError("rows and labels require string case_id and constraint_id")
    return case_id, constraint_id


def _label_index(
    labels: Sequence[Mapping[str, Any] | Any] | Mapping[tuple[str, str], Mapping[str, Any] | Any],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    if isinstance(labels, Mapping):
        return {key: _record(value) for key, value in labels.items()}
    indexed: dict[tuple[str, str], Mapping[str, Any]] = {}
    for label in labels:
        normalized = _record(label)
        key = _key(normalized)
        if key in indexed:
            raise ValueError(f"duplicate labels for {key!r}")
        indexed[key] = normalized
    return indexed


def _metadata_index(
    metadata: Sequence[Mapping[str, Any] | Any]
    | Mapping[tuple[str, str], Mapping[str, Any] | Any]
    | None,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    if metadata is None:
        return {}
    if isinstance(metadata, Mapping):
        return {key: _record(value) for key, value in metadata.items()}
    return {_key(_record(item)): _record(item) for item in metadata}


def _episode_runs(rows: Sequence[Mapping[str, Any]]) -> list[list[int]]:
    """Return grouped alert episodes as their observed absolute sequences.

    The sorted evaluated rows define adjacency; a no-alert or abstention ends an
    episode. This avoids treating every monitored prefix as a separate UX alert.
    """
    episodes: list[list[int]] = []
    active: list[int] | None = None
    for row in sorted(rows, key=lambda item: int(item["prefix_seq"])):
        is_alert = row.get("decision") == "alert" and _eligible_for_alert(row)
        if is_alert:
            if active is None:
                active = []
                episodes.append(active)
            active.append(int(row["prefix_seq"]))
        else:
            active = None
    return episodes


def _eligible_for_alert(row: Mapping[str, Any]) -> bool:
    """Whether an evaluated prefix can contribute to alert metrics."""
    return row.get("eligible_for_alert", True) is True


def _eligible_action_event(row: Mapping[str, Any]) -> bool:
    """Whether a source event belongs in action-event denominators.

    New producers should emit ``action_event_eligible``. The legacy
    ``eligible_for_alert`` fallback keeps old stored runs interpretable until
    their producers add the separate field.
    """
    value = row.get("action_event_eligible", row.get("eligible_for_action_event"))
    if value is None:
        value = row.get("eligible_for_alert", True)
    return value is True


def _median(values: list[int]) -> float | None:
    return float(statistics.median(values)) if values else None


def _number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"stored {field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"stored {field} must be finite and non-negative")
    return number


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _operational_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize operational metadata once per semantic request/call.

    Batched Jev rows repeat the same usage fields for every constraint answer.
    ``call_id`` is therefore the deduplication boundary. Legacy rows without a
    call ID retain the previous one-row accounting behavior.
    """
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    units: list[Mapping[str, Any]] = []
    for row in rows:
        call_id = row.get("call_id")
        if isinstance(call_id, str) and call_id:
            group_key: tuple[Any, ...] = ("call", call_id)
            grouped[group_key].append(row)
        elif (
            (
                row.get("error_code") == "offline_cache_miss"
                or isinstance(row.get("from_cache"), bool)
                or isinstance(row.get("provider_call_made"), bool)
            )
            and isinstance(row.get("case_id"), str)
            and isinstance(row.get("prefix_seq"), int)
        ):
            # Jev cache misses can abstain before a call ID exists. A single
            # case/prefix still represents one batched semantic request.
            grouped[("request", row["case_id"], row["prefix_seq"])].append(row)
        else:
            units.append(row)
    operational_fields = (
        "call_count",
        "call_made",
        "network_call",
        "provider_call_made",
        "from_cache",
        "usage",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "estimated_cost_usd",
        "latency_seconds",
        "error",
        "error_code",
    )
    for group_key, call_rows in grouped.items():
        first = {field: call_rows[0].get(field) for field in operational_fields}
        for row in call_rows[1:]:
            current = {field: row.get(field) for field in operational_fields}
            if current != first:
                raise ValueError(f"operational metadata differs within request group {group_key!r}")
        units.append(call_rows[0])
    call_count_values: list[float] = []
    input_tokens: list[float] = []
    output_tokens: list[float] = []
    costs: list[float] = []
    live_costs: list[float] = []
    latencies: list[float] = []
    error_calls = 0
    provider_calls = 0
    cache_hits = 0
    cache_misses = 0
    for row in units:
        provider_made = row.get("provider_call_made")
        if not isinstance(provider_made, bool):
            if isinstance(row.get("call_made"), bool):
                provider_made = row["call_made"]
            elif isinstance(row.get("network_call"), bool):
                provider_made = row["network_call"]
            elif isinstance(row.get("from_cache"), bool):
                provider_made = not row["from_cache"]
        if row.get("error_code") == "offline_cache_miss":
            cache_misses += 1
        elif row.get("from_cache") is True or provider_made is False:
            cache_hits += 1
        elif row.get("from_cache") is False or provider_made is True:
            cache_misses += 1
        if "call_count" in row:
            count = _number(row["call_count"], "call_count")
            call_count_values.append(count)
            if provider_made is not False:
                provider_calls += int(count)
        elif provider_made is True:
            call_count_values.append(1.0)
            provider_calls += 1
        usage = row.get("usage")
        usage_input_seen = False
        usage_output_seen = False
        if usage is not None:
            if not isinstance(usage, Mapping):
                raise ValueError("stored usage must be a mapping")
            if "input_tokens" in usage:
                input_tokens.append(_number(usage["input_tokens"], "input_tokens"))
                usage_input_seen = True
            if "output_tokens" in usage:
                output_tokens.append(_number(usage["output_tokens"], "output_tokens"))
                usage_output_seen = True
        for field, destination in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
        ):
            if field in row and not (
                (field == "input_tokens" and usage_input_seen)
                or (field == "output_tokens" and usage_output_seen)
            ):
                destination.append(_number(row[field], field))
        for field in ("cost_usd", "estimated_cost_usd"):
            if field in row:
                cost = _number(row[field], field)
                costs.append(cost)
                if provider_made is not False:
                    live_costs.append(cost)
                break
        if "latency_seconds" in row and provider_made is not False:
            latencies.append(_number(row["latency_seconds"], "latency_seconds"))
        error = row.get("error")
        if error is True or (isinstance(error, str) and error) or row.get("error_code"):
            error_calls += 1
    return {
        "stored_call_count": sum(call_count_values) if call_count_values else None,
        "stored_call_count_observed": bool(call_count_values),
        "semantic_request_groups": len(units) if units else None,
        "provider_call_count": provider_calls
        if (provider_calls or cache_hits or cache_misses or call_count_values)
        else None,
        "cache_hit_count": cache_hits if (cache_hits or cache_misses) else None,
        "cache_miss_count": cache_misses if (cache_hits or cache_misses) else None,
        "input_tokens_total": sum(input_tokens) if input_tokens else None,
        "output_tokens_total": sum(output_tokens) if output_tokens else None,
        "cost_usd_total": sum(costs) if costs else None,
        "cost_usd_this_run": sum(live_costs) if live_costs else (0.0 if cache_hits else None),
        "latency_observations": len(latencies),
        "latency_p50_seconds": _percentile(latencies, 0.50),
        "latency_p95_seconds": _percentile(latencies, 0.95),
        "error_rows": error_calls,
        "error_call_count": error_calls,
        "error_rate": error_calls / len(units) if units else None,
    }


def _bootstrap_uncertainty(
    grouped_rows: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    labels: Mapping[tuple[str, str], Mapping[str, Any]],
    metadata: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    replicates: int,
    seed: int,
    min_cases: int,
) -> dict[str, Any]:
    """Bootstrap primary rates by resampling complete case trajectories."""
    case_ids = sorted(
        {
            case_id
            for case_id, constraint_id in grouped_rows
            if labels.get((case_id, constraint_id), {}).get("outcome") in GRADEABLE_OUTCOMES
        }
    )
    result: dict[str, Any] = {
        "unit": "trajectory",
        "confidence_level": 0.95,
        "replicates": replicates,
        "seed": seed,
        "minimum_trajectories": min_cases,
        "trajectory_count": len(case_ids),
        "suppressed": False,
        "intervals": {},
    }
    if len(case_ids) < min_cases:
        result["suppressed"] = True
        result["reason"] = "too few gradeable trajectories for uncertainty interval"
        return result
    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    rng = random.Random(seed)
    metric_names = (
        "compliant_case_constraint_false_alert_rate",
        "compliant_trajectory_false_alert_rate",
        "violation_recall_at_or_after_onset",
        "observable_early_warning_coverage",
    )
    samples: dict[str, list[float]] = {name: [] for name in metric_names}
    for replicate in range(replicates):
        sampled = rng.choices(case_ids, k=len(case_ids))
        sampled_grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
        sampled_labels: dict[tuple[str, str], Mapping[str, Any]] = {}
        sampled_metadata: dict[tuple[str, str], Mapping[str, Any]] = {}
        for draw, case_id in enumerate(sampled):
            synthetic_case = f"{case_id}#bootstrap-{replicate}-{draw}"
            for (original_case, constraint_id), rows in grouped_rows.items():
                if original_case != case_id:
                    continue
                unit = (synthetic_case, constraint_id)
                sampled_grouped[unit] = list(rows)
                if unit_label := labels.get((original_case, constraint_id)):
                    sampled_labels[unit] = unit_label
                if unit_metadata := metadata.get((original_case, constraint_id)):
                    sampled_metadata[unit] = unit_metadata
        summary = _summarize(sampled_grouped, sampled_labels, sampled_metadata)
        for name in metric_names:
            value = summary[name]
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            ):
                samples[name].append(float(value))
    for name, values in samples.items():
        if values:
            result["intervals"][name] = {
                "lower": _percentile(values, 0.025),
                "upper": _percentile(values, 0.975),
            }
    return result


def _summarize(
    grouped_rows: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    labels: Mapping[tuple[str, str], Mapping[str, Any]],
    metadata: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    compliant_units: list[tuple[str, str]] = []
    violated_units: list[tuple[str, str]] = []
    all_gradeable_units: list[tuple[str, str]] = []
    compliant_alerts = 0
    false_episodes = 0
    eligible_action_events: set[tuple[str, str]] = set()
    detected = 0
    lags: list[int] = []
    early_eligible = 0
    early_detected = 0
    abstentions_all = 0
    evaluated_all = 0
    abstentions_gradeable = 0
    evaluated_gradeable = 0
    excluded_unknown_units = 0
    pre_onset_alert_episodes = 0
    pre_onset_false_alert_episodes = 0

    for unit, rows in sorted(grouped_rows.items()):
        label = labels.get(unit)
        outcome = label.get("outcome") if label else None
        evaluated_all += len(rows)
        abstentions_all += sum(row.get("decision") == "abstain" for row in rows)
        if outcome not in GRADEABLE_OUTCOMES:
            excluded_unknown_units += 1
            continue
        if label is None:
            continue
        all_gradeable_units.append(unit)
        evaluated_gradeable += len(rows)
        abstentions_gradeable += sum(row.get("decision") == "abstain" for row in rows)
        episodes = _episode_runs(rows)
        alert_sequences = [seq for episode in episodes for seq in episode]
        for row in rows:
            if _eligible_action_event(row):
                action_id = row.get("action_event_id", row["prefix_seq"])
                eligible_action_events.add((unit[0], str(action_id)))
        if outcome == "compliant":
            compliant_units.append(unit)
            false_episodes += len(episodes)
            compliant_alerts += int(bool(episodes))
            continue

        violated_units.append(unit)
        onset = label.get("first_clear_violation_seq")
        if not isinstance(onset, int) or isinstance(onset, bool):
            raise ValueError("violated labels require integer first_clear_violation_seq")
        post_onset = [seq for seq in alert_sequences if seq >= onset]
        if post_onset:
            detected += 1
            lags.append(post_onset[0] - onset)
        pre_onset_episodes = [
            episode for episode in episodes if any(seq < onset for seq in episode)
        ]
        pre_onset_alert_episodes += len(pre_onset_episodes)
        justified_window: tuple[int, int] | None = None
        if label.get("pre_effect_warning_possible") is True:
            risk_start = label.get("earliest_observable_risk_seq")
            first_effect = label.get("first_effect_seq", onset)
            if (
                isinstance(risk_start, int)
                and not isinstance(risk_start, bool)
                and isinstance(first_effect, int)
                and not isinstance(first_effect, bool)
                and risk_start < first_effect
            ):
                early_eligible += 1
                justified_window = (risk_start, first_effect)
                early_detected += int(
                    any(risk_start <= seq < first_effect for seq in alert_sequences)
                )
        for episode in pre_onset_episodes:
            if justified_window is None or not any(
                justified_window[0] <= seq < justified_window[1] for seq in episode
            ):
                pre_onset_false_alert_episodes += 1

    labels_by_case: dict[str, list[tuple[tuple[str, str], Mapping[str, Any]]]] = defaultdict(list)
    for unit, label in labels.items():
        labels_by_case[unit[0]].append((unit, label))
    all_compliant_cases = {
        case_id
        for case_id, items in labels_by_case.items()
        if items
        and all(item[1].get("outcome") == "compliant" and item[0] in grouped_rows for item in items)
    }
    false_alert_cases = {
        case_id
        for case_id, constraint_id in compliant_units
        if _episode_runs(grouped_rows[(case_id, constraint_id)])
    }
    # A safe trajectory is all of its gradeable constraints being compliant.
    safe_false_alert_cases = false_alert_cases & all_compliant_cases
    supplied_label_count = len(labels)
    timing_labeled_units = sum(
        1
        for label in labels.values()
        if any(
            isinstance(label.get(field), int) and not isinstance(label.get(field), bool)
            for field in ("first_clear_violation_seq", "first_attempt_seq", "first_effect_seq")
        )
    )
    pre_effect_labeled_units = sum(
        1
        for label in labels.values()
        if label.get("pre_effect_warning_possible") is not None
        and isinstance(label.get("earliest_observable_risk_seq"), int)
        and isinstance(label.get("first_effect_seq"), int)
    )
    case_prefixes: dict[str, set[int]] = defaultdict(set)
    for (case_id, _constraint_id), unit_rows in grouped_rows.items():
        case_prefixes[case_id].update(int(row["prefix_seq"]) for row in unit_rows)
    trajectory_count_with_multiple_events = sum(
        len(prefixes) > 1 for prefixes in case_prefixes.values()
    )

    return {
        **_operational_summary([row for rows in grouped_rows.values() for row in rows]),
        "case_constraint_units": len(grouped_rows),
        "gradeable_case_constraint_units": len(all_gradeable_units),
        "excluded_unknown_or_ungradeable_units": excluded_unknown_units,
        "evaluated_rows": evaluated_all,
        "abstention_rows": abstentions_all,
        "abstention_rate": abstentions_all / evaluated_all if evaluated_all else None,
        "gradeable_evaluated_rows": evaluated_gradeable,
        "gradeable_abstention_rows": abstentions_gradeable,
        "gradeable_abstention_rate": abstentions_gradeable / evaluated_gradeable
        if evaluated_gradeable
        else None,
        "compliant_case_constraint_units": len(compliant_units),
        "compliant_case_constraint_false_alerts": compliant_alerts,
        "compliant_case_constraint_false_alert_rate": compliant_alerts / len(compliant_units)
        if compliant_units
        else None,
        "all_compliant_trajectories": len(all_compliant_cases),
        "all_compliant_trajectories_with_alert": len(safe_false_alert_cases),
        "compliant_trajectory_false_alert_rate": len(safe_false_alert_cases)
        / len(all_compliant_cases)
        if all_compliant_cases
        else None,
        "false_alert_episodes": false_episodes,
        "eligible_action_events": len(eligible_action_events),
        "false_alert_episodes_per_100_eligible_action_events": (
            100 * false_episodes / len(eligible_action_events) if eligible_action_events else None
        ),
        "violated_case_constraint_units": len(violated_units),
        "detected_violations_at_or_after_onset": detected,
        "violation_recall_at_or_after_onset": detected / len(violated_units)
        if violated_units
        else None,
        "detection_lag_sequence_deltas": lags,
        "median_detection_lag_sequence_delta": _median(lags),
        "pre_onset_alert_episodes_on_violations": pre_onset_alert_episodes,
        "pre_onset_false_alert_episodes_on_violations": pre_onset_false_alert_episodes,
        "observable_early_warning_eligible_units": early_eligible,
        "observable_early_warning_detected_units": early_detected,
        "observable_early_warning_coverage": early_detected / early_eligible
        if early_eligible
        else None,
        "timing_labeled_units": timing_labeled_units,
        "timing_label_coverage": timing_labeled_units / supplied_label_count
        if supplied_label_count
        else None,
        "pre_effect_warning_labeled_units": pre_effect_labeled_units,
        "pre_effect_warning_label_coverage": pre_effect_labeled_units / supplied_label_count
        if supplied_label_count
        else None,
        "trajectory_count_with_multiple_events": trajectory_count_with_multiple_events,
    }


def build_metrics(
    rows: Sequence[Mapping[str, Any] | Any],
    labels: Sequence[Mapping[str, Any] | Any] | Mapping[tuple[str, str], Mapping[str, Any] | Any],
    metadata: Sequence[Mapping[str, Any] | Any]
    | Mapping[tuple[str, str], Mapping[str, Any] | Any]
    | None = None,
    *,
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    bootstrap_min_cases: int = BOOTSTRAP_MIN_CASES,
) -> dict[str, Any]:
    """Compute deterministic metrics from stored results only, without network access."""
    normalized_rows = [_record(row) for row in rows]
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in normalized_rows:
        decision = row.get("decision")
        if not isinstance(decision, str) or decision not in {"alert", "no_alert", "abstain"}:
            raise ValueError("result decision must be alert, no_alert, or abstain")
        prefix_seq = row.get("prefix_seq")
        if not isinstance(prefix_seq, int) or isinstance(prefix_seq, bool) or prefix_seq < 0:
            raise ValueError("result prefix_seq must be a non-negative integer")
        grouped[_key(row)].append(row)
    label_index = _label_index(labels)
    metadata_index = _metadata_index(metadata)
    for unit, unit_rows in grouped.items():
        sequences = [row["prefix_seq"] for row in unit_rows]
        if len(sequences) != len(set(sequences)):
            raise ValueError(f"duplicate result rows for {unit!r}")
    evaluator_identities = {
        canonical_bytes(row.get("evaluator", row.get("evaluator_id", "unspecified")))
        for row in normalized_rows
    }
    if len(evaluator_identities) > 1:
        raise ValueError("mixed evaluator runs must be reported separately")
    primary = _summarize(grouped, label_index, metadata_index)
    primary["uncertainty"] = _bootstrap_uncertainty(
        grouped,
        label_index,
        metadata_index,
        replicates=bootstrap_replicates,
        seed=bootstrap_seed,
        min_cases=bootstrap_min_cases,
    )
    labels_with_rows = set(grouped) & set(label_index)
    labels_without_rows = set(label_index) - set(grouped)
    primary.update(
        {
            "labels_supplied": len(label_index),
            "labels_with_evaluated_rows": len(labels_with_rows),
            "labels_without_evaluated_rows": len(labels_without_rows),
            "label_evaluation_coverage_rate": len(labels_with_rows) / len(label_index)
            if label_index
            else None,
            "rows_without_labels": sum(
                len(unit_rows) for unit, unit_rows in grouped.items() if unit not in label_index
            ),
        }
    )

    def stratify(field: str) -> dict[str, dict[str, Any]]:
        subsets: dict[str, dict[tuple[str, str], list[Mapping[str, Any]]]] = defaultdict(dict)
        for unit, unit_rows in grouped.items():
            name = metadata_index.get(unit, {}).get(field, "unknown")
            subsets[str(name)][unit] = unit_rows
        return {
            name: _summarize(subset, label_index, metadata_index)
            for name, subset in sorted(subsets.items())
        }

    return {
        "metric_spec_version": "metrics-v1",
        "primary": primary,
        "by_category": stratify("category"),
        "by_oracle_kind": stratify("oracle_kind"),
    }


def _markdown(metrics: Mapping[str, Any]) -> str:
    primary = metrics["primary"]
    lines = [
        "# Offline evaluation metrics",
        "",
        "This report was computed solely from stored evaluator results and labels; it made no API calls.",
        "Unknown and ungradeable labels are excluded from primary false-alert and recall denominators.",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for name in (
        "compliant_case_constraint_false_alert_rate",
        "compliant_trajectory_false_alert_rate",
        "false_alert_episodes_per_100_eligible_action_events",
        "violation_recall_at_or_after_onset",
        "median_detection_lag_sequence_delta",
        "observable_early_warning_coverage",
        "gradeable_abstention_rate",
    ):
        lines.append(f"| {name} | {primary[name]} |")
    lines.extend(["", "## Counts", ""])
    for name in sorted(primary):
        if (
            name.endswith("_rate")
            or name.endswith("_coverage")
            or name == "false_alert_episodes_per_100_eligible_action_events"
            or name == "median_detection_lag_sequence_delta"
        ):
            continue
        lines.append(f"- {name}: {primary[name]}")
    return "\n".join(lines) + "\n"


def write_report(metrics: Mapping[str, Any], output_dir: Path | str) -> tuple[Path, Path]:
    """Write stable JSON and Markdown artifacts; no provider adapter is involved."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "metrics.json"
    markdown_path = directory / "report.md"
    json_path.write_bytes(canonical_bytes(metrics) + b"\n")
    markdown_path.write_text(_markdown(metrics), encoding="utf-8", newline="\n")
    return json_path, markdown_path


def write_metrics_csv(metrics: Mapping[str, Any], output_path: Path | str) -> Path:
    """Write deterministic primary metrics as a two-column CSV artifact."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("metric", "value"))
        for name in sorted(metrics["primary"]):
            writer.writerow((name, metrics["primary"][name]))
    return path
