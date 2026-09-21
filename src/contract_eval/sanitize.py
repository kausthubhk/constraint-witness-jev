"""Deterministic redaction for trace-derived publication candidates."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----.*?-----END [A-Z ]+ PRIVATE KEY-----", re.S),
    re.compile(
        r"(?i)\b(?:[a-z][a-z0-9]*[_-])*"
        r"(?:api[_-]?key|secret|token|password|authorization|credential)\s*[:=]\s*[^\s,;]+"
    ),
)
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/)(?:[^\s\\/]+[\\/]){1,}[^\s]*")
_DATA_BLOB = re.compile(r"(?i)^data:[^;,]+;base64,[A-Za-z0-9+/=]{32,}$")
_LONG_B64 = re.compile(r"^[A-Za-z0-9+/]{128,}={0,2}$")
_SENSITIVE_KEY = re.compile(
    r"(?i)(?:^|[_-])(?:api[_-]?key|secret|password|authorization|credential|"
    r"private[_-]?key|(?:access|refresh|id)?[_-]?token)$"
)


@dataclass
class SanitizationReport:
    redactions: int = 0
    oversized_values: int = 0
    sensitive_fields: int = 0
    findings: list[str] = field(default_factory=list)

    @property
    def publication_allowed(self) -> bool:
        return not self.findings


def _redact_string(value: str, report: SanitizationReport, *, max_string_chars: int) -> str:
    if len(value) > max_string_chars:
        report.oversized_values += 1
        report.redactions += 1
        report.findings.append("oversized string")
        return f"<REDACTED oversized string: {len(value)} chars>"
    if _DATA_BLOB.match(value) or _LONG_B64.match(value):
        report.redactions += 1
        report.findings.append("binary/base64 blob")
        return "<REDACTED blob>"
    replaced = value
    for pattern in _SECRET_PATTERNS:
        replaced, count = pattern.subn("<REDACTED secret>", replaced)
        if count:
            report.sensitive_fields += count
            report.redactions += count
            report.findings.append("secret-like value")
    replaced, count = _ABSOLUTE_PATH.subn("<REDACTED path>", replaced)
    if count:
        report.redactions += count
        report.findings.append("absolute path")
    return replaced


def sanitize_value(
    value: Any,
    *,
    report: SanitizationReport | None = None,
    max_string_chars: int = 16_384,
    max_collection_items: int = 10_000,
) -> Any:
    """Return a JSON-compatible sanitized copy and populate ``report``."""
    if max_string_chars < 1 or max_collection_items < 1:
        raise ValueError("sanitization limits must be positive")
    report = report or SanitizationReport()
    if isinstance(value, str):
        return _redact_string(value, report, max_string_chars=max_string_chars)
    if isinstance(value, float) and not isfinite(value):
        report.redactions += 1
        report.findings.append("non-finite number")
        return "<REDACTED non-finite number>"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_collection_items:
                report.redactions += 1
                report.findings.append("oversized object")
                break
            key_text = _redact_string(str(key), report, max_string_chars=max_string_chars)
            if _SENSITIVE_KEY.search(str(key)):
                report.sensitive_fields += 1
                report.redactions += 1
                report.findings.append("secret-like field")
                result[key_text] = "<REDACTED secret>"
            else:
                result[key_text] = sanitize_value(
                    item,
                    report=report,
                    max_string_chars=max_string_chars,
                    max_collection_items=max_collection_items,
                )
        return result
    if isinstance(value, (list, tuple)):
        items: list[Any] = [
            sanitize_value(
                item,
                report=report,
                max_string_chars=max_string_chars,
                max_collection_items=max_collection_items,
            )
            for item in value[:max_collection_items]
        ]
        if len(value) > max_collection_items:
            report.redactions += 1
            report.findings.append("oversized array")
        return items
    return value


def sanitize_jsonl_records(
    records: Iterable[dict[str, Any]], *, max_records: int = 100_000, **kwargs: Any
) -> tuple[list[dict[str, Any]], SanitizationReport]:
    """Sanitize a bounded iterable of JSON objects without retaining raw input."""
    if max_records < 1:
        raise ValueError("max_records must be positive")
    report = SanitizationReport()
    output: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        if index > max_records:
            raise ValueError(f"JSONL sanitization exceeds {max_records} records")
        if not isinstance(record, dict):
            raise ValueError("JSONL sanitization requires JSON object records")
        output.append(sanitize_value(record, report=report, **kwargs))
    return output, report
