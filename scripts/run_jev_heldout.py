"""Run the frozen held-out cohort through the canonical Jev run writer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.cli import eval_jev  # noqa: E402
from contract_eval.jev import load_frozen_config  # noqa: E402
from contract_eval.schema import Case, DatasetManifest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs/evaluators/jev-heldout-synthetic-v1.json"
    )
    parser.add_argument(
        "--jev-config", type=Path, default=ROOT / "configs/evaluators/jev-contract-monitor-v1.json"
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=ROOT / ".jev-cache" / "heldout-synthetic-v1"
    )
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / "results" / "private" / "jev-heldout-synthetic-v1"
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    config: dict[str, Any] = json.loads(args.config.read_text(encoding="utf-8"))
    frozen = load_frozen_config(args.jev_config)
    if config.get("status") != "heldout_pending_live_evaluation":
        raise ValueError("held-out configuration is not pending live evaluation")
    if config.get("evaluator_spec_sha256") != frozen.get("evaluator_spec_sha256"):
        raise ValueError("held-out configuration does not match frozen evaluator")
    if config.get("representations") != frozen.get("representations"):
        raise ValueError("held-out representations differ from frozen evaluator")
    dataset = ROOT / str(config["dataset"])
    manifest = DatasetManifest.model_validate_json(
        (dataset / "manifest.json").read_text(encoding="utf-8")
    )
    if len(manifest.case_ids) < int(config["minimum_case_count"]):
        raise ValueError("held-out cohort count is below the configured minimum")
    # Count raw case records without changing them; this script never regenerates held-out data.
    cases = [
        Case.model_validate_json((dataset / f"{case_id}.json").read_text(encoding="utf-8"))
        for case_id in manifest.case_ids
    ]
    prefix_count = sum(len(case.events) for case in cases)
    if prefix_count != int(config["expected_prefixes"]):
        raise ValueError("held-out prefix count mismatch")
    if prefix_count * len(config["representations"]) != int(config["expected_prefix_evaluations"]):
        raise ValueError("held-out prefix evaluation count mismatch")
    for representation in config["representations"]:
        eval_jev(
            dataset,
            args.out_dir / f"{representation}.jsonl",
            representation=representation,
            jev_config=args.jev_config,
            cache_dir=args.cache_dir,
            live=args.live,
            force=args.force,
        )
    print(
        json.dumps(
            {
                "status": "completed",
                "runs": len(config["representations"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
