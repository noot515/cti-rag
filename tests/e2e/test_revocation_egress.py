from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.evidence.lifecycle import LifecycleAuthority, VisibilityExpired
from packages.evidence.policy import ResolvedScope
from packages.evidence.snapshot import SnapshotCatalog
from packages.evidence.store import EvidenceStore


def _scope():
    return ResolvedScope(
        principal_id="1",
        principal_namespace="user.id",
        corpus_id="opencti",
        domain="cti",
        scope_id="scope",
        active_catalog_id="g",
        policy_version="v1",
        source_allowlist=frozenset({"opencti"}),
        allowed_destinations=frozenset({"caller", "reranker_provider"}),
    )


def test_revision_tombstone_overrides_retained_snapshot(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        now = "2026-09-18T00:00:00Z"
        store.connection.execute(
            "INSERT INTO objects(domain,scope_id,object_uid) VALUES('cti','scope','o')"
        )
        store.connection.execute(
            "INSERT INTO object_revisions(domain,scope_id,object_uid,revision_uid,payload_json,lifecycle_state,created_at) VALUES('cti','scope','o','r','{}','active',?)",
            (now,),
        )
        store.connection.execute(
            "INSERT INTO tombstones(domain,scope_id,evidence_kind,evidence_uid,revision_uid,reason,tombstoned_at) VALUES('cti','scope','object','o','r','revoked',?)",
            (now,),
        )
        catalog = SnapshotCatalog(store)
        manifest = SimpleNamespace(domain="cti", scope_id="scope")
        assert catalog.withdrawn(manifest, "object", "o", "r") is True


def test_expired_visibility_stops_egress_before_provider_call(tmp_path: Path):
    calls = {"provider": 0}
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
        with pytest.raises(VisibilityExpired):
            authority.assert_scope_current(
                _scope(),
                now=datetime(2026, 9, 18, 0, 2, 0, tzinfo=timezone.utc),
            )
        # The provider is intentionally after the freshness gate.
        assert calls["provider"] == 0
