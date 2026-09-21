"""Run the pinned development smoke through the canonical Jev run writer."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.cli import eval_jev  # noqa: E402
from contract_eval.jev import load_frozen_config  # noqa: E402
from contract_eval.schema import Case  # noqa: E402


def _load_selected(config: Mapping[str, Any]) -> dict[str, Case]:
    dataset = ROOT / str(config["dataset"])
    selected = config.get("cases")
    if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
        raise ValueError("smoke config cases must be a list of case IDs")
    if len(selected) != len(set(selected)):
        raise ValueError("smoke config contains duplicate case IDs")
    cases = {
        case_id: Case.model_validate_json((dataset / f"{case_id}.json").read_text(encoding="utf-8"))
        for case_id in selected
    }
    if len(cases) != config.get("expected_case_count"):
        raise ValueError("smoke config case count mismatch")
    if sum(len(case.constraints) for case in cases.values()) != config.get(
        "expected_constraint_units"
    ):
        raise ValueError("smoke config constraint count mismatch")
    if sum(len(case.events) for case in cases.values()) != config.get("expected_prefixes"):
        raise ValueError("smoke config prefix count mismatch")
    return cases


def _gate_prefix(case: Case, constraint_id: str, selector: str) -> int:
    constraint = next((item for item in case.constraints if item.id == constraint_id), None)
    if constraint is None:
        raise ValueError(f"smoke gate references unknown constraint {case.case_id}/{constraint_id}")
    if selector == "final":
        if not case.events:
            raise ValueError(f"smoke gate case has no events: {case.case_id}")
        return case.events[-1].seq
    if selector == "first_clear_violation":
        label = case.labels.get(constraint_id)
        if label is None or label.first_clear_violation_event is None:
            raise ValueError(f"smoke gate lacks first-clear label: {case.case_id}/{constraint_id}")
        return next(
            event.seq for event in case.events if event.id == label.first_clear_violation_event
        )
    raise ValueError(f"unsupported smoke gate prefix selector: {selector}")


def validate_development_smoke_gate(
    rows: Sequence[Mapping[str, Any]], config: Mapping[str, Any], cases: Mapping[str, Case]
) -> dict[str, int]:
    """Require explicit configured controls to separate for every representation."""
    gate = config.get("development_smoke_gate")
    representations = config.get("representations")
    threshold = config.get("threshold")
    if (
        not isinstance(gate, Mapping)
        or not isinstance(representations, list)
        or not all(isinstance(item, str) for item in representations)
        or not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
    ):
        raise ValueError("smoke config has no valid executable separation gate")
    index: dict[tuple[object, object, object, object], Mapping[str, Any]] = {}
    for row in rows:
        evaluator = row.get("evaluator")
        representation = (
            evaluator.get("projection_version") if isinstance(evaluator, Mapping) else None
        )
        index[
            (row.get("case_id"), row.get("constraint_id"), row.get("prefix_seq"), representation)
        ] = row
    checked = 0
    checks = (
        ("compliant", lambda score: score < float(threshold)),
        ("violated", lambda score: score >= float(threshold)),
    )
    for expected, comparator in checks:
        controls = gate.get(expected)
        if not isinstance(controls, list) or not controls:
            raise ValueError(f"smoke gate has no {expected} controls")
        for control in controls:
            if not isinstance(control, Mapping):
                raise ValueError("smoke gate control is invalid")
            case_id = control.get("case_id")
            constraint_id = control.get("constraint_id")
            selector = control.get("prefix")
            if (
                not isinstance(case_id, str)
                or not isinstance(constraint_id, str)
                or not isinstance(selector, str)
            ):
                raise ValueError("smoke gate control is invalid")
            case = cases.get(case_id)
            if case is None:
                raise ValueError(f"smoke gate references unselected case {case_id}")
            prefix = _gate_prefix(case, constraint_id, selector)
            for representation in representations:
                row = index.get((case_id, constraint_id, prefix, representation))
                score = row.get("score") if row is not None else None
                if (
                    not isinstance(score, (int, float))
                    or isinstance(score, bool)
                    or not comparator(float(score))
                ):
                    raise ValueError(
                        f"development smoke separation failed: {expected} {case_id}/{constraint_id} "
                        f"at {representation} prefix {prefix}"
                    )
                checked += 1
    return {"checked_control_scores": checked, "representations": len(representations)}


def _read_rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs/evaluators/jev-development-smoke-v1.json"
    )
    parser.add_argument(
        "--jev-config", type=Path, default=ROOT / "configs/evaluators/jev-contract-monitor-v1.json"
    )
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".jev-cache" / "development")
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / "results" / "private" / "jev-development-smoke-v1"
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    frozen = load_frozen_config(args.jev_config)
    if config.get("status") != "development_only" or config.get("max_development_iterations") != 1:
        raise ValueError("smoke configuration is not the pinned one-iteration development protocol")
    if config.get("representations") != frozen.get("representations"):
        raise ValueError("smoke representations differ from frozen evaluator")
    if config.get("threshold") != frozen.get("threshold"):
        raise ValueError("smoke threshold differs from frozen evaluator")
    cases = _load_selected(config)
    all_rows: list[dict[str, Any]] = []
    for representation in config["representations"]:
        output = args.out_dir / f"{representation}.jsonl"
        eval_jev(
            ROOT / str(config["dataset"]),
            output,
            representation=representation,
            jev_config=args.jev_config,
            cache_dir=args.cache_dir,
            live=args.live,
            force=args.force,
            case_ids=set(config["cases"]),
        )
        all_rows.extend(_read_rows(output))
    result = validate_development_smoke_gate(all_rows, config, cases)
    gate_output = args.out_dir / "development-smoke-gate.json"
    if gate_output.exists():
        raise ValueError(f"smoke gate output already exists: {gate_output}")
    gate_output.write_text(
        json.dumps({"status": "passed", **result}, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"status": "passed", "runs": len(config["representations"]), **result},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
