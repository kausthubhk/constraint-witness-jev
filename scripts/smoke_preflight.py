"""Validate and account for the pinned development smoke cohort.

This command is deliberately offline. It never reads an API key and never
constructs a network transport. It is intended to run immediately before a
separate, explicitly authorized live runner.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.canonical import canonical_bytes  # noqa: E402
from contract_eval.replay import evaluator_state, evaluator_state_sha256  # noqa: E402
from contract_eval.schema import Case, DatasetManifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs/evaluators/jev-development-smoke-v1.json",
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    dataset = ROOT / str(config["dataset"])
    manifest = DatasetManifest.model_validate_json(
        (dataset / "manifest.json").read_text(encoding="utf-8")
    )
    selected = list(config["cases"])
    if len(selected) != len(set(selected)):
        raise SystemExit("smoke config contains duplicate case IDs")
    if set(selected) - set(manifest.case_ids):
        raise SystemExit("smoke config references a case absent from the dataset manifest")

    cases: list[Case] = []
    for case_id in selected:
        case_path = dataset / f"{case_id}.json"
        if not case_path.is_file():
            raise SystemExit(f"missing selected case: {case_path}")
        cases.append(Case.model_validate_json(case_path.read_text(encoding="utf-8")))

    prefixes = sum(len(case.events) for case in cases)
    units = sum(len(case.constraints) for case in cases)
    batched = prefixes
    expected = {
        "cases": len(cases),
        "constraint_units": units,
        "prefixes": prefixes,
        "batched_calls_per_representation": batched,
        "batched_calls_both_representations": batched * 2,
    }
    config_keys = {
        "cases": "expected_case_count",
        "constraint_units": "expected_constraint_units",
        "prefixes": "expected_prefixes",
        "batched_calls_per_representation": "expected_batched_calls_per_representation",
        "batched_calls_both_representations": "expected_batched_calls_both_representations",
    }
    for key, value in expected.items():
        if value != config[config_keys[key]]:
            raise SystemExit(f"config count mismatch for {key}: {value}")

    hashes_differ = 0
    state_hashes: list[dict[str, object]] = []
    for case in cases:
        for event in case.events:
            raw = evaluator_state(case, event.seq, "normalized_raw")
            projected = evaluator_state(case, event.seq, "policy_projection_v1")
            state_hashes.extend(
                {
                    "case_id": case.case_id,
                    "prefix_seq": event.seq,
                    "representation": representation,
                    "evaluator_state_sha256": evaluator_state_sha256(
                        case, event.seq, representation
                    ),
                }
                for representation in ("normalized_raw", "policy_projection_v1")
            )
            if canonical_bytes(raw) != canonical_bytes(projected):
                hashes_differ += 1
            raw_text = json.dumps(raw, sort_keys=True)
            projected_text = json.dumps(projected, sort_keys=True)
            forbidden = ("labels", "raw_ref", "source_metadata")
            if any(token in raw_text or token in projected_text for token in forbidden):
                raise SystemExit(f"forbidden evaluator field in {case.case_id} prefix {event.seq}")

    if hashes_differ == 0:
        raise SystemExit("raw and projected representations never differ in this cohort")
    print(
        json.dumps(
            {
                "status": "ok",
                "hash_different_prefixes": hashes_differ,
                "state_hashes": state_hashes,
                **expected,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
