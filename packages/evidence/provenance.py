"""Provenance and revision-projection helpers."""
from __future__ import annotations

from hashlib import sha256
from typing import Any, Iterable, Mapping

from .ids import canonical_json


def raw_payload_sha256(payload: Any) -> str:
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def unique_source_ref_keys(source_refs: Iterable[object]) -> tuple[tuple[str, str, str, str], ...]:
    keys = []
    for ref in source_refs:
        keys.append((str(getattr(ref, "domain")), str(getattr(ref, "source_instance")),
                     str(getattr(ref, "source_object_id")), str(getattr(ref, "raw_payload_sha256"))))
    return tuple(dict.fromkeys(keys))


def canonical_revision_projection(*, source_instance: str, source_object_id: str,
                                  upstream_origin: str, source_uri: str | None,
                                  normalizer_version: str, semantic_fields: Mapping[str, Any],
                                  policy_fields: Mapping[str, Any], evidence_locators: Iterable[str] = ()) -> dict[str, Any]:
    """Return the canonical revision-bearing projection.

    Capture-only state such as source snapshot IDs, retry/poll timestamps, and raw-byte
    formatting hashes is deliberately absent. Repeated raw captures are associated
    separately through SourceRef/RawCaptureRef rather than manufacturing revisions.
    """
    return {
        "source": {
            "source_instance": source_instance,
            "source_object_id": source_object_id,
            "upstream_origin": upstream_origin,
            "source_uri": source_uri,
        },
        "normalizer_version": normalizer_version,
        "evidence_locators": sorted(set(evidence_locators)),
        "semantic": dict(semantic_fields),
        "policy": dict(policy_fields),
    }
