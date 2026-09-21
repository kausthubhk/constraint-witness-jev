"""Canonical JSON and hashes used for reproducible state identities."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def _normalise(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=False)
    if isinstance(value, dict):
        return {
            str(key): _normalise(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n")
    return value


def canonical_bytes(value: Any) -> bytes:
    """Encode values as sorted, UTF-8 JSON while preserving null versus absence."""
    return json.dumps(
        _normalise(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
