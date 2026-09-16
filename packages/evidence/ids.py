"""Versioned, domain-separated evidence identity functions."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from .validation import assert_json_safe, utc_json


def _canonicalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc_json(value)
    if isinstance(value, Mapping):
        return {key: _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    assert_json_safe(value)
    return json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_hash(parts: Iterable[Any]) -> str:
    payload = canonical_json(list(parts)).encode("utf-8")
    return sha256(payload).hexdigest()


def object_uid(domain: str, source_instance: str, source_object_id: str) -> str:
    return canonical_hash(["object-v2", domain, source_instance, source_object_id])


def revision_uid(object_id: str, canonical_source_content: Any) -> str:
    return canonical_hash(["revision-v2", object_id, canonical_source_content])


def relation_uid(
    *,
    domain: str,
    source_instance: str,
    source_record_id: str,
    source_object_uid: str,
    target_object_uid: str,
    normalized_relation: str,
    source_field_path: str | None = None,
    qualifiers: Any = None,
    upstream_relation_id: str | None = None,
) -> str:
    if upstream_relation_id:
        return canonical_hash(["relation-v2", domain, source_instance, upstream_relation_id])
    return canonical_hash(
        [
            "relation-v2",
            domain,
            source_instance,
            source_record_id,
            source_field_path,
            source_object_uid,
            target_object_uid,
            normalized_relation,
            qualifiers or [],
        ]
    )


def relation_revision_uid(relation_id: str, canonical_source_content: Any) -> str:
    return canonical_hash(["relation-revision-v2", relation_id, canonical_source_content])


def chunk_uid(
    *,
    object_id: str,
    object_revision_id: str,
    chunker_fingerprint: str,
    section_path: str,
    ordinal: int,
    content_hash: str,
) -> str:
    return canonical_hash(
        [
            "chunk-v2",
            object_id,
            object_revision_id,
            chunker_fingerprint,
            section_path,
            ordinal,
            content_hash,
        ]
    )


def path_uid(
    ordered_node_uids: Iterable[str],
    ordered_relation_revision_uids: Iterable[str],
    traversal_directions: Iterable[str],
) -> str:
    return canonical_hash(
        [
            "path-v2",
            list(ordered_node_uids),
            list(ordered_relation_revision_uids),
            list(traversal_directions),
        ]
    )
