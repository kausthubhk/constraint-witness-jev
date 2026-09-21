import io
import json

import pytest

from contract_eval.ingest import TraceIngestError, iter_jsonl_records
from contract_eval.release import (
    check_provider_result_publication,
    check_publication_cases,
    check_publication_value,
)
from contract_eval.sanitize import sanitize_jsonl_records, sanitize_value


def test_jsonl_ingest_is_bounded_and_preserves_line_number() -> None:
    data = b'{"id": 1}\n{"id": 2}\n'
    records = list(iter_jsonl_records(io.BytesIO(data), max_records=2))
    assert [record.value["id"] for record in records] == [1, 2]

    with pytest.raises(TraceIngestError, match="exceeds 1 records") as error:
        list(iter_jsonl_records(io.BytesIO(data), max_records=1))
    assert error.value.line_number == 2


def test_jsonl_ingest_rejects_invalid_utf8_and_malformed_json() -> None:
    with pytest.raises(TraceIngestError, match="UTF-8"):
        list(iter_jsonl_records(io.BytesIO(b'{"ok": 1}\n\xff\n')))
    with pytest.raises(TraceIngestError, match="malformed"):
        list(iter_jsonl_records(io.BytesIO(b'{"ok": 1}\n{"broken"\n')))


def test_sanitizer_redacts_secrets_paths_and_blobs() -> None:
    value = {
        "api_key": "secret-value",
        "token": "Bearer abcdefghijklmnop",
        "text": "open C:\\Users\\alice\\private.txt",
        "blob": "data:application/octet-stream;base64," + ("A" * 40),
    }
    sanitized = sanitize_value(value)
    assert sanitized["api_key"] == "<REDACTED secret>"
    assert "abcdefghijklmnop" not in json.dumps(sanitized)
    assert "C:\\Users\\alice" not in json.dumps(sanitized)
    assert "<REDACTED blob>" in sanitized["blob"]


def test_sanitizer_catches_prefixed_credential_names_and_bounds_record_collections() -> None:
    sanitized = sanitize_value(
        {
            "TYPESAFE_API_KEY": "provider-secret",
            "OPENAI_API_KEY": "other-secret",
            "nested": "CODEX_API_KEY=third-secret",
            "value": float("nan"),
        }
    )
    serialized = json.dumps(sanitized)
    assert "provider-secret" not in serialized
    assert "other-secret" not in serialized
    assert "third-secret" not in serialized
    assert "NaN" not in serialized
    with pytest.raises(ValueError, match="exceeds 1 records"):
        sanitize_jsonl_records([{"ok": 1}, {"ok": 2}], max_records=1)
    with pytest.raises(ValueError, match="JSON object"):
        sanitize_jsonl_records([{"ok": 1}, ["not-an-object"]])  # type: ignore[list-item]


def test_publication_check_fails_closed_on_sensitive_or_unresolved_content() -> None:
    result = check_publication_value({"text": "token=super-secret-value"})
    assert not result.passed
    assert any(issue.code == "unsanitized-content" for issue in result.issues)


def test_release_checks_malformed_source_and_aggregates_all_sanitization_reports() -> None:
    malformed = check_publication_cases(
        [
            {"source": None, "token": "one-secret"},
            {"source": {"license": "CC0", "redistribution_allowed": True}, "token": "two-secret"},
        ]
    )
    assert any(issue.code == "source-provenance-invalid" for issue in malformed.issues)
    assert malformed.sanitization is not None
    assert malformed.sanitization.sensitive_fields == 2


def test_provider_result_release_gate_fails_closed_until_permission_is_resolved() -> None:
    run = [{"case_id": "case", "raw_response_sha256": "a" * 64, "decision": "alert"}]
    blocked = check_provider_result_publication(run)
    assert not blocked.passed
    assert any(
        issue.code == "provider-result-publication-permission-unresolved"
        for issue in blocked.issues
    )
    allowed = check_provider_result_publication(run, provider_publication_allowed=True)
    assert not any(
        issue.code == "provider-result-publication-permission-unresolved"
        for issue in allowed.issues
    )
