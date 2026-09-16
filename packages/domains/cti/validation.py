"""CTI-specific structural validation helpers."""

from __future__ import annotations

import re

_STIX_ID_RE = re.compile(
    r"^[a-z][a-z0-9-]*--[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def validate_stix_id(value: str) -> str:
    if _STIX_ID_RE.fullmatch(value) is None:
        raise ValueError(f"invalid STIX identifier: {value}")
    return value


def require_synthetic_fixture(value: bool) -> None:
    if value is not True:
        raise ValueError("bundled CTI fixture records must declare synthetic=true")
