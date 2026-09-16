from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from .validation import assert_json_safe, require_sha256, utc_json


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
    return json.dumps(_canonicalize(value), ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def canonical_hash(parts: Iterable[Any]) -> str:
    return sha256(canonical_json(list(parts)).encode("utf-8")).hexdigest()


def object_uid(domain: str, source_instance: str, source_object_id: str) -> str:
    return canonical_hash(["object-v2", domain, source_instance, source_object_id])


def revision_uid(object_id: str, canonical_source_content: Any) -> str:
    require_sha256(object_id, field_name="object_id")
    return canonical_hash(["revision-v2", object_id, canonical_source_content])


def relation_uid(*, domain: str, source_instance: str, source_record_id: str, source_object_uid: str,
                 target_object_uid: str, normalized_relation: str, source_field_path: str | None = None,
                 qualifiers: Any = None, upstream_relation_id: str | None = None) -> str:
    require_sha256(source_object_uid, field_name="source_object_uid")
    require_sha256(target_object_uid, field_name="target_object_uid")
    if upstream_relation_id:
        return canonical_hash(["relation-v2", domain, source_instance, upstream_relation_id])
    return canonical_hash(["relation-v2", domain, source_instance, source_record_id, source_field_path,
                           source_object_uid, target_object_uid, normalized_relation, qualifiers or []])


def relation_revision_uid(relation_id: str, canonical_source_content: Any) -> str:
    require_sha256(relation_id, field_name="relation_id")
    return canonical_hash(["relation-revision-v2", relation_id, canonical_source_content])


def chunk_uid(*, object_id: str, object_revision_id: str, chunker_fingerprint: str,
              section_path: str, ordinal: int, content_hash: str) -> str:
    require_sha256(object_id, field_name="object_id")
    require_sha256(object_revision_id, field_name="object_revision_id")
    require_sha256(content_hash, field_name="content_hash")
    return canonical_hash(["chunk-v2", object_id, object_revision_id, chunker_fingerprint,
                           section_path, ordinal, content_hash])


def path_uid(ordered_node_uids: Iterable[str], ordered_relation_revision_uids: Iterable[str],
             traversal_directions: Iterable[str]) -> str:
    nodes = list(ordered_node_uids)
    relations = list(ordered_relation_revision_uids)
    directions = list(traversal_directions)
    for value in [*nodes, *relations]:
        require_sha256(value)
    return canonical_hash(["path-v2", nodes, relations, directions])


def physical_key(scope_id: str, logical_uid: str) -> str:
    require_sha256(logical_uid, field_name="logical_uid")
    if not scope_id:
        raise ValueError("scope_id must not be empty")
    return canonical_hash(["physical-v1", scope_id, logical_uid])
