from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "run_jev_development_smoke.py"
SPEC = importlib.util.spec_from_file_location("run_jev_development_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def _gate_rows(config, cases, *, broken: bool = False):
    rows = []
    for expected, score in (("compliant", 0.1), ("violated", 0.9)):
        for control in config["development_smoke_gate"][expected]:
            prefix = smoke._gate_prefix(
                cases[control["case_id"]], control["constraint_id"], control["prefix"]
            )
            for representation in config["representations"]:
                rows.append(
                    {
                        "case_id": control["case_id"],
                        "constraint_id": control["constraint_id"],
                        "prefix_seq": prefix,
                        "evaluator": {"projection_version": representation},
                        "score": 0.8 if broken and expected == "compliant" else score,
                    }
                )
    return rows


def test_development_smoke_gate_uses_explicit_configured_controls() -> None:
    config = json.loads((ROOT / "configs/evaluators/jev-development-smoke-v1.json").read_text())
    cases = smoke._load_selected(config)
    result = smoke.validate_development_smoke_gate(_gate_rows(config, cases), config, cases)
    assert result["checked_control_scores"] == 18
    with pytest.raises(ValueError, match="separation failed"):
        smoke.validate_development_smoke_gate(_gate_rows(config, cases, broken=True), config, cases)
