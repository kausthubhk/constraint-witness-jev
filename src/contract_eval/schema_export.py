"""Generate and check the versioned public JSON Schema bundle."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes
from .schema import (
    AgentProvenance,
    Case,
    Constraint,
    ConstraintStatusTransition,
    DatasetManifest,
    EvaluationResult,
    EvaluatorConfig,
    Event,
    FileChange,
    GroundTruth,
    InstructionSurface,
    OracleSpec,
    RunCaseIdentity,
    RunManifest,
    SourceProvenance,
    TelemetryCapabilities,
)

EXPORT_FORMAT = "contract-eval-json-schema-v1"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "schemas" / "contract-eval-v1.json"

MODELS = (
    SourceProvenance,
    AgentProvenance,
    InstructionSurface,
    OracleSpec,
    ConstraintStatusTransition,
    Constraint,
    FileChange,
    TelemetryCapabilities,
    Event,
    GroundTruth,
    Case,
    EvaluatorConfig,
    EvaluationResult,
    DatasetManifest,
    RunCaseIdentity,
    RunManifest,
)


def schema_bundle() -> dict[str, Any]:
    """Return deterministic JSON Schema exports for the public Pydantic records."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "format": EXPORT_FORMAT,
        "models": {model.__name__: model.model_json_schema() for model in MODELS},
    }


def rendered_schema_bundle() -> bytes:
    return canonical_bytes(schema_bundle()) + b"\n"


def export_schema(output: Path = DEFAULT_OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(rendered_schema_bundle())


def schema_is_current(output: Path = DEFAULT_OUTPUT) -> bool:
    try:
        return output.read_bytes() == rendered_schema_bundle()
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the contract-eval JSON Schema bundle")
    parser.add_argument(
        "--check", action="store_true", help="fail when the checked-in export is stale"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if args.check:
        if schema_is_current(args.output):
            print(f"schema export is current: {args.output}")
            return 0
        print(f"schema export is stale or missing: {args.output}")
        return 1
    export_schema(args.output)
    print(f"wrote schema export: {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
