"""Provenance helpers that keep source evidence immutable and explicit."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Iterable

from .ids import canonical_json


def raw_payload_sha256(payload: Any) -> str:
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def unique_source_ref_keys(source_refs: Iterable[object]) -> tuple[tuple[str, str, str, str], ...]:
    keys = []
    for ref in source_refs:
        keys.append(
            (
                str(getattr(ref, "domain")),
                str(getattr(ref, "source_instance")),
                str(getattr(ref, "source_object_id")),
                str(getattr(ref, "raw_payload_sha256")),
            )
        )
    return tuple(dict.fromkeys(keys))
