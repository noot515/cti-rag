from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from packages.evidence.lifecycle import LifecycleAuthority, VisibilityExpired
from packages.evidence.policy import ResolvedScope
from packages.evidence.store import EvidenceStore


def _seed_revision(store, *, source_id: str, object_uid: str, revision_uid: str):
    digest = sha256(source_id.encode()).hexdigest()
    store.raw_store.put(source_id.encode(), expected_sha256=digest)
    now = "2026-09-18T00:00:00Z"
    db = store.connection
    db.execute(
        "INSERT OR IGNORE INTO raw_payloads(domain,scope_id,sha256,byte_length,created_at) VALUES('cti','scope',?,?,?)",
        (digest, len(source_id), now),
    )
    db.execute(
        "INSERT OR IGNORE INTO objects(domain,scope_id,object_uid) VALUES('cti','scope',?)",
        (object_uid,),
    )
    db.execute(
        "INSERT OR IGNORE INTO object_revisions(domain,scope_id,object_uid,revision_uid,payload_json,lifecycle_state,created_at) VALUES('cti','scope',?,?,?,'active',?)",
        (object_uid, revision_uid, '{"object_type":"vulnerability"}', now),
    )
    db.execute(
        "INSERT OR IGNORE INTO object_revision_sources(domain,scope_id,revision_uid,raw_sha256,source_instance,source_object_id) VALUES('cti','scope',?,?,?,?)",
        (revision_uid, digest, "opencti", source_id),
    )


def _scope():
    return ResolvedScope(
        principal_id="1",
        principal_namespace="user.id",
        corpus_id="opencti",
        domain="cti",
        scope_id="scope",
        active_catalog_id="g1",
        policy_version="v1",
        source_allowlist=frozenset({"opencti"}),
        allowed_destinations=frozenset({"caller"}),
    )


def test_complete_inventory_tombstones_missing_but_incomplete_inventory_does_not(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        _seed_revision(store, source_id="visible-a", object_uid="a", revision_uid="ra")
        authority = LifecycleAuthority(store)
        incomplete = authority.record_inventory(
            domain="cti", scope_id="scope", source_instance="opencti",
            supported_type="vulnerability", type_fingerprint="type-v1",
            filter_fingerprint="filter-v1", seen_source_ids=(),
            current_revisions={}, explicit_status={}, complete=False,
            authorized=True, page_count=0,
            capture_started_at="2026-09-18T00:00:00Z",
            capture_completed_at="2026-09-18T00:00:01Z",
            max_staleness_seconds=3600, failure_reason="timeout",
        )
        assert incomplete.complete is False
        assert store.connection.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0] == 0
        assert store.connection.execute("SELECT COUNT(*) FROM visibility_leases").fetchone()[0] == 0

        complete = authority.record_inventory(
            domain="cti", scope_id="scope", source_instance="opencti",
            supported_type="vulnerability", type_fingerprint="type-v1",
            filter_fingerprint="filter-v1", seen_source_ids=(),
            current_revisions={}, explicit_status={}, complete=True,
            authorized=True, page_count=1,
            capture_started_at="2026-09-18T00:01:00Z",
            capture_completed_at="2026-09-18T00:01:01Z",
            max_staleness_seconds=3600,
        )
        assert complete.tombstones_written == 1
        row = store.connection.execute("SELECT reason FROM tombstones").fetchone()
        assert row["reason"] == "no_longer_visible"


def test_marking_revision_retires_old_revision_without_hiding_current(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        _seed_revision(store, source_id="same", object_uid="o", revision_uid="old")
        _seed_revision(store, source_id="same", object_uid="o", revision_uid="new")
        authority = LifecycleAuthority(store)
        authority.record_inventory(
            domain="cti", scope_id="scope", source_instance="opencti",
            supported_type="vulnerability", type_fingerprint="type-v1",
            filter_fingerprint="filter-v1", seen_source_ids=("same",),
            current_revisions={"same": {("object", "o", "new")}},
            explicit_status={}, complete=True, authorized=True, page_count=1,
            capture_started_at="2026-09-18T00:00:00Z",
            capture_completed_at="2026-09-18T00:00:01Z",
            max_staleness_seconds=3600,
        )
        rows = store.connection.execute(
            "SELECT revision_uid,reason FROM tombstones ORDER BY revision_uid"
        ).fetchall()
        assert [(row["revision_uid"], row["reason"]) for row in rows] == [
            ("old", "no_longer_visible")
        ]


def test_explicit_revoke_is_stronger_than_missing_classification(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        _seed_revision(store, source_id="same", object_uid="o", revision_uid="r")
        authority = LifecycleAuthority(store)
        authority.record_inventory(
            domain="cti", scope_id="scope", source_instance="opencti",
            supported_type="vulnerability", type_fingerprint="type-v1",
            filter_fingerprint="filter-v1", seen_source_ids=("same",),
            current_revisions={"same": {("object", "o", "r")}},
            explicit_status={"same": "revoked"}, complete=True, authorized=True,
            page_count=1,
            capture_started_at="2026-09-18T00:00:00Z",
            capture_completed_at="2026-09-18T00:00:01Z",
            max_staleness_seconds=3600,
        )
        assert store.connection.execute(
            "SELECT reason FROM tombstones"
        ).fetchone()["reason"] == "revoked"


def test_merge_mapping_preserves_provenance_and_retires_source(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        _seed_revision(store, source_id="source", object_uid="source-o", revision_uid="rs")
        _seed_revision(store, source_id="target", object_uid="target-o", revision_uid="rt")
        authority = LifecycleAuthority(store)
        assert authority.record_merge(
            domain="cti", scope_id="scope",
            source_object_uid="source-o", target_object_uid="target-o",
            source_instance="opencti",
            provenance={"event_id": "merge-1", "kind": "explicit"},
        ) == 1
        mapping = store.connection.execute(
            "SELECT provenance_json FROM evidence_merge_mappings"
        ).fetchone()
        assert "merge-1" in mapping["provenance_json"]
        assert store.connection.execute(
            "SELECT reason FROM tombstones WHERE evidence_uid='source-o'"
        ).fetchone()["reason"] == "no_longer_visible"


def test_lease_expiry_fails_closed(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        authority = LifecycleAuthority(store)
        authority.record_inventory(
            domain="cti", scope_id="scope", source_instance="opencti",
            supported_type="vulnerability", type_fingerprint="type-v1",
            filter_fingerprint="filter-v1", seen_source_ids=(),
            current_revisions={}, explicit_status={}, complete=True,
            authorized=True, page_count=1,
            capture_started_at="2026-09-18T00:00:00Z",
            capture_completed_at="2026-09-18T00:00:01Z",
            max_staleness_seconds=60,
        )
        authority.assert_scope_current(
            _scope(),
            now=datetime(2026, 9, 18, 0, 0, 30, tzinfo=timezone.utc),
        )
        with pytest.raises(VisibilityExpired):
            authority.assert_scope_current(
                _scope(),
                now=datetime(2026, 9, 18, 0, 2, 0, tzinfo=timezone.utc),
            )



def test_inventory_is_type_scoped_and_does_not_tombstone_other_types(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        _seed_revision(
            store,
            source_id="vuln",
            object_uid="v",
            revision_uid="rv",
        )
        digest = sha256(b"report").hexdigest()
        store.raw_store.put(b"report", expected_sha256=digest)
        store.connection.execute(
            "INSERT INTO raw_payloads(domain,scope_id,sha256,byte_length,created_at) VALUES('cti','scope',?,?,?)",
            (digest, 6, "2026-09-18T00:00:00Z"),
        )
        store.connection.execute(
            "INSERT INTO objects(domain,scope_id,object_uid) VALUES('cti','scope','report-o')"
        )
        store.connection.execute(
            "INSERT INTO object_revisions(domain,scope_id,object_uid,revision_uid,payload_json,lifecycle_state,created_at) "
            "VALUES('cti','scope','report-o','report-r','{\"object_type\":\"report\"}','active','2026-09-18T00:00:00Z')"
        )
        store.connection.execute(
            "INSERT INTO object_revision_sources(domain,scope_id,revision_uid,raw_sha256,source_instance,source_object_id) "
            "VALUES('cti','scope','report-r',?,'opencti','report')",
            (digest,),
        )
        authority = LifecycleAuthority(store)
        authority.record_inventory(
            domain="cti", scope_id="scope", source_instance="opencti",
            supported_type="vulnerability", type_fingerprint="type-v1",
            filter_fingerprint="filter-v1", seen_source_ids=("vuln",),
            current_revisions={"vuln": {("object", "v", "rv")}},
            explicit_status={}, complete=True, authorized=True, page_count=1,
            capture_started_at="2026-09-18T00:00:00Z",
            capture_completed_at="2026-09-18T00:00:01Z",
            max_staleness_seconds=3600,
        )
        assert store.connection.execute(
            "SELECT COUNT(*) FROM tombstones WHERE evidence_uid='report-o'"
        ).fetchone()[0] == 0
