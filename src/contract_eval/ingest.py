"""Bounded, offline JSONL ingestion helpers.

The importer deliberately accepts records as untrusted bytes.  It never reads
environment variables and does not interpret provider-specific event payloads;
normalization belongs to the caller.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

DEFAULT_MAX_LINE_BYTES = 1_048_576
DEFAULT_MAX_RECORDS = 100_000


class TraceIngestError(ValueError):
    """A JSONL input violated the bounded ingestion contract."""

    def __init__(self, message: str, *, line_number: int | None = None) -> None:
        super().__init__(message)
        self.line_number = line_number


@dataclass(frozen=True)
class JsonlRecord:
    line_number: int
    value: dict[str, Any]


def iter_jsonl_records(
    source: str | Path | IO[bytes],
    *,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
    max_records: int = DEFAULT_MAX_RECORDS,
    allow_blank_lines: bool = True,
    invalid_utf8: str = "error",
) -> Iterator[JsonlRecord]:
    """Yield bounded JSON objects from a UTF-8 JSONL source.

    ``invalid_utf8`` is intentionally either ``"error"`` or ``"skip"``.
    Replacement decoding is not supported because it can silently change
    evidence and hashes.
    """
    if max_line_bytes < 1 or max_records < 1:
        raise ValueError("limits must be positive")
    if invalid_utf8 not in {"error", "skip"}:
        raise ValueError("invalid_utf8 must be 'error' or 'skip'")
    close = False
    if isinstance(source, (str, Path)):
        handle: IO[bytes] = open(source, "rb")
        close = True
    else:
        handle = source
    count = 0
    try:
        for line_number, raw_line in enumerate(handle, start=1):
            if len(raw_line) > max_line_bytes:
                raise TraceIngestError(
                    f"JSONL line exceeds {max_line_bytes} bytes", line_number=line_number
                )
            if not raw_line.strip():
                if allow_blank_lines:
                    continue
                raise TraceIngestError("blank JSONL line is not allowed", line_number=line_number)
            try:
                text = raw_line.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                if invalid_utf8 == "skip":
                    continue
                raise TraceIngestError(
                    "JSONL line is not valid UTF-8", line_number=line_number
                ) from exc
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise TraceIngestError("malformed JSONL record", line_number=line_number) from exc
            if not isinstance(value, dict):
                raise TraceIngestError(
                    "JSONL record must be a JSON object", line_number=line_number
                )
            count += 1
            if count > max_records:
                raise TraceIngestError(
                    f"JSONL input exceeds {max_records} records", line_number=line_number
                )
            yield JsonlRecord(line_number, value)
    finally:
        if close:
            handle.close()


def read_jsonl_bounded(source: str | Path | IO[bytes], **kwargs: Any) -> list[JsonlRecord]:
    """Materialize a bounded JSONL source after applying stream limits."""
    return list(iter_jsonl_records(source, **kwargs))


def read_jsonl_bounded_with_sha256(
    source: str | Path | IO[bytes], **kwargs: Any
) -> tuple[list[JsonlRecord], str]:
    """Read bounded JSONL records while hashing the exact bytes consumed.

    The hash is over the source bytes, including blank lines and line endings.
    Parsing uses the same bytes, so callers never hash a reserialized object.
    """
    max_line_bytes = int(kwargs.pop("max_line_bytes", DEFAULT_MAX_LINE_BYTES))
    max_records = int(kwargs.pop("max_records", DEFAULT_MAX_RECORDS))
    allow_blank_lines = bool(kwargs.pop("allow_blank_lines", True))
    invalid_utf8 = str(kwargs.pop("invalid_utf8", "error"))
    if kwargs:
        raise TypeError(f"unsupported JSONL options: {', '.join(kwargs)}")
    if max_line_bytes < 1 or max_records < 1:
        raise ValueError("limits must be positive")
    if invalid_utf8 not in {"error", "skip"}:
        raise ValueError("invalid_utf8 must be 'error' or 'skip'")
    close = False
    if isinstance(source, (str, Path)):
        handle: IO[bytes] = open(source, "rb")
        close = True
    else:
        handle = source
    digest = hashlib.sha256()
    records: list[JsonlRecord] = []
    try:
        for line_number, raw_line in enumerate(handle, start=1):
            digest.update(raw_line)
            if len(raw_line) > max_line_bytes:
                raise TraceIngestError(
                    f"JSONL line exceeds {max_line_bytes} bytes", line_number=line_number
                )
            if not raw_line.strip():
                if allow_blank_lines:
                    continue
                raise TraceIngestError("blank JSONL line is not allowed", line_number=line_number)
            try:
                text = raw_line.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                if invalid_utf8 == "skip":
                    continue
                raise TraceIngestError(
                    "JSONL line is not valid UTF-8", line_number=line_number
                ) from exc
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise TraceIngestError("malformed JSONL record", line_number=line_number) from exc
            if not isinstance(value, dict):
                raise TraceIngestError(
                    "JSONL record must be a JSON object", line_number=line_number
                )
            records.append(JsonlRecord(line_number, value))
            if len(records) > max_records:
                raise TraceIngestError(
                    f"JSONL input exceeds {max_records} records", line_number=line_number
                )
    finally:
        if close:
            handle.close()
    return records, digest.hexdigest()
