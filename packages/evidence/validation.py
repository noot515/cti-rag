"""Pure validation helpers shared by generic evidence contracts."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def require_sha256(value: str, *, field_name: str = "sha256") -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase 64-character SHA-256 hex digest")
    return value


def normalize_utc_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.replace("Z", "+00:00")
        value = datetime.fromisoformat(candidate)
    if not isinstance(value, datetime):
        raise TypeError("timestamp must be a datetime or ISO-8601 string")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an explicit timezone")
    return value.astimezone(timezone.utc)


def utc_json(value: datetime) -> str:
    normalized = normalize_utc_datetime(value)
    assert normalized is not None
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def require_finite(value: float, *, field_name: str = "score") -> float:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")
    return value


def assert_json_safe(value: Any, *, path: str = "$") -> None:
    """Reject Python-only values before they enter revision identity or traces."""
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, datetime):
        normalize_utc_datetime(value)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_json_safe(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            assert_json_safe(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} contains non-JSON-safe value of type {type(value).__name__}")
