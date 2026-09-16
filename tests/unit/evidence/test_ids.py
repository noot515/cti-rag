from __future__ import annotations

from packages.evidence.ids import canonical_hash, object_uid, path_uid, physical_key, revision_uid
from packages.evidence.provenance import canonical_revision_projection


def test_golden_object_and_revision_hashes_are_stable():
    uid = object_uid("cti", "fixture-public", "record-1")
    projection = canonical_revision_projection(
        source_instance="fixture-public",
        source_object_id="record-1",
        upstream_origin="synthetic",
        source_uri="fixture://record-1",
        normalizer_version="v1",
        semantic_fields={"name": "Example", "aliases": ["Ex"]},
        policy_fields={"dissemination": ["tlp:clear"]},
        evidence_locators=["description"],
    )
    assert uid == "8055a10d28af08513875d36b22cf39134beb93315ce525f1615ccf57b60fb09e"
    assert revision_uid(uid, projection) == "f2b7877b5211f0436ac99d4972ba23e75161f08e227483ddbe8408ce6e98f8f1"


def test_retry_capture_metadata_does_not_change_revision_projection():
    first = canonical_revision_projection(
        source_instance="s", source_object_id="1", upstream_origin="origin", source_uri=None,
        normalizer_version="n1", semantic_fields={"name": "same"}, policy_fields={}, evidence_locators=[])
    second = canonical_revision_projection(
        source_instance="s", source_object_id="1", upstream_origin="origin", source_uri=None,
        normalizer_version="n1", semantic_fields={"name": "same"}, policy_fields={}, evidence_locators=[])
    uid = object_uid("cti", "s", "1")
    assert revision_uid(uid, first) == revision_uid(uid, second)
    changed_marking = canonical_revision_projection(
        source_instance="s", source_object_id="1", upstream_origin="origin", source_uri=None,
        normalizer_version="n1", semantic_fields={"name": "same"},
        policy_fields={"dissemination": ["tlp:amber"]}, evidence_locators=[]
    )
    assert revision_uid(uid, first) != revision_uid(uid, changed_marking)


def test_object_uid_stays_stable_when_stix_identifier_appears_later():
    before = object_uid("cti", "upstream", "stable-record-id")
    after = object_uid("cti", "upstream", "stable-record-id")
    assert before == after
    assert revision_uid(before, {"name": "x", "stix_id": None}) != revision_uid(after, {"name": "x", "stix_id": "vulnerability--abc"})


def test_reverse_traversal_and_scope_physical_keys_are_distinct():
    a = object_uid("cti", "s", "a")
    b = object_uid("cti", "s", "b")
    rel_rev = canonical_hash(["relation-revision-v2", "r"])
    assert path_uid([a, b], [rel_rev], ["forward"]) != path_uid([a, b], [rel_rev], ["reverse"])
    assert physical_key("scope-a", a) != physical_key("scope-b", a)
