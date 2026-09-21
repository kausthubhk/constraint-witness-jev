from __future__ import annotations

from contract_eval.schema_export import (
    export_schema,
    rendered_schema_bundle,
    schema_bundle,
    schema_is_current,
)


def test_schema_bundle_exports_every_public_pydantic_record() -> None:
    bundle = schema_bundle()
    assert bundle["format"] == "contract-eval-json-schema-v1"
    assert {"Case", "Event", "GroundTruth", "EvaluationResult"} <= set(bundle["models"])
    assert bundle["models"]["Case"]["additionalProperties"] is False


def test_schema_export_check_detects_stale_or_missing_output(tmp_path) -> None:
    output = tmp_path / "schema.json"
    assert schema_is_current(output) is False
    export_schema(output)
    assert output.read_bytes() == rendered_schema_bundle()
    assert schema_is_current(output) is True
    output.write_text("{}\n", encoding="utf-8")
    assert schema_is_current(output) is False
