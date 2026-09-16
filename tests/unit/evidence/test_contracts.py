from __future__ import annotations

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from packages.evidence.ids import canonical_hash, chunk_uid, object_uid, path_uid, relation_uid, revision_uid
from packages.evidence.schema import EvidenceObject, EvidencePath, EvidencePolicyMetadata, ExternalIdentifier, SnapshotRef, SourceRef


def _source_ref(domain: str = "cti") -> SourceRef:
    return SourceRef(domain=domain, source_instance="fixture-public", source_object_id="record-1",
                     upstream_origin="synthetic-fixture", source_uri="fixture://record-1",
                     raw_payload_sha256="a" * 64, source_snapshot_id="snapshot-1",
                     normalizer_version="normalizer-v1")


def test_object_and_revision_identity_are_domain_separated():
    content = {"name": "Shared normalized name", "modified": "2026-09-16T00:00:00Z"}
    cti_uid = object_uid("cti", "fixture", "same-source-id")
    networking_uid = object_uid("networking", "fixture", "same-source-id")
    assert cti_uid != networking_uid
    assert revision_uid(cti_uid, content) != revision_uid(networking_uid, content)


def test_canonical_hash_uses_unambiguous_json_and_utc_normalization():
    first = canonical_hash(["x", {"b": 2, "a": datetime(2026, 9, 16, tzinfo=timezone.utc)}])
    second = canonical_hash(["x", {"a": "2026-09-16T00:00:00.000000Z", "b": 2}])
    assert first == second
    assert canonical_hash(["ab", "c"]) != canonical_hash(["a", "bc"])


def test_generic_evidence_round_trip_is_json_safe_and_typed():
    uid = object_uid("cti", "fixture-public", "record-1")
    rev = revision_uid(uid, {"name": "fixture"})
    obj = EvidenceObject(uid=uid, revision_uid=rev, domain="cti", scope_id="public-fixture",
                         object_type="vulnerability", name="Fixture",
                         external_ids=(ExternalIdentifier(namespace="cve", value="CVE-2026-999999", domain="cti"),),
                         source_refs=(_source_ref(),), created_at="2026-09-16T00:00:00+00:00",
                         policy=EvidencePolicyMetadata(source_instances=("fixture-public",)))
    restored = EvidenceObject.model_validate_json(obj.model_dump_json())
    assert restored == obj
    assert restored.created_at.utcoffset().total_seconds() == 0


def test_generic_timestamp_requires_timezone():
    uid = object_uid("cti", "fixture-public", "record-1")
    rev = revision_uid(uid, {"name": "fixture"})
    with pytest.raises(ValidationError, match="explicit timezone"):
        EvidenceObject(uid=uid, revision_uid=rev, domain="cti", scope_id="public-fixture",
                       object_type="vulnerability", source_refs=(_source_ref(),), created_at="2026-09-16T00:00:00")


def test_relation_identity_preserves_independent_assertions_with_same_endpoints():
    source_uid = object_uid("cti", "fixture", "source")
    target_uid = object_uid("cti", "fixture", "target")
    first = relation_uid(domain="cti", source_instance="fixture", source_record_id="record-a",
                         source_field_path="refs[0]", source_object_uid=source_uid, target_object_uid=target_uid,
                         normalized_relation="maps_to")
    second = relation_uid(domain="cti", source_instance="fixture", source_record_id="record-b",
                          source_field_path="secondary_refs[0]", source_object_uid=source_uid, target_object_uid=target_uid,
                          normalized_relation="maps_to")
    assert first != second


def test_chunk_and_path_identity_include_revision_and_direction():
    uid = object_uid("cti", "fixture", "source")
    rev1 = revision_uid(uid, {"version": 1})
    rev2 = revision_uid(uid, {"version": 2})
    content_hash = "b" * 64
    chunk1 = chunk_uid(object_id=uid, object_revision_id=rev1, chunker_fingerprint="chunker-v1",
                       section_path="description", ordinal=0, content_hash=content_hash)
    chunk2 = chunk_uid(object_id=uid, object_revision_id=rev2, chunker_fingerprint="chunker-v1",
                       section_path="description", ordinal=0, content_hash=content_hash)
    assert chunk1 != chunk2
    relation_revision = "c" * 64
    target = object_uid("cti", "fixture", "target")
    assert path_uid([uid, target], [relation_revision], ["forward"]) != path_uid([uid, target], [relation_revision], ["reverse"])


def test_evidence_path_rejects_inconsistent_shape():
    snapshot = SnapshotRef(domain="cti", scope_id="public-fixture", snapshot_id="snapshot-1", manifest_sha256="e" * 64)
    with pytest.raises(ValidationError, match="one more node"):
        EvidencePath(path_id="d" * 64, domain="cti", scope_id="public-fixture", snapshot=snapshot,
                     ordered_node_uids=("a" * 64,), ordered_node_revision_uids=("f" * 64,),
                     ordered_relation_revision_uids=("b" * 64,), traversal_directions=("forward",),
                     domains_traversed=("cti",))
