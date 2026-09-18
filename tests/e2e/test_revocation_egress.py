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



def test_orchestrator_rechecks_freshness_before_reranker_provider():
    from dataclasses import dataclass

    from packages.evidence.ids import canonical_hash
    from packages.evidence.policy import Principal
    from packages.evidence.schema import (
        AuthorizedEvidenceView,
        ChannelScore,
        EvidencePolicyMetadata,
        ObjectCandidate,
        RetrievalRequest,
        SnapshotRef,
    )
    from packages.retrieval.candidate import ChannelResult
    from packages.retrieval.orchestrator import AdvancedRetrievalOrchestrator
    from packages.retrieval.planner import DeterministicQueryPlanner

    class Adapter:
        domain = "cti"
        def parse_identifiers(self, query): return []
        def allowed_graph_patterns(self, hint): return []
        def infer_task_hint(self, query, identifiers): return "general"
        def requested_target_types(self, query, identifiers, task): return ()

    class FreshnessPolicy:
        def __init__(self):
            self.checks = 0
        def resolve_scope(self, principal, corpus):
            return ResolvedScope(
                principal_id=principal.principal_id,
                corpus_id=corpus,
                domain="cti",
                scope_id="scope",
                policy_version="v1",
                source_allowlist=frozenset({"opencti"}),
                allowed_destinations=frozenset({"caller", "reranker_provider"}),
            )
        def assert_scope_current(self, scope):
            self.checks += 1
            if self.checks >= 2:
                raise VisibilityExpired("corpus-access-denied")

    @dataclass
    class Handle:
        snapshot: SnapshotRef
        manifest: object = None
        def __enter__(self): return self
        def __exit__(self, *args): return False

    class Snapshots:
        def pin_active(self, scope):
            return Handle(SnapshotRef(
                domain="cti", scope_id="scope", snapshot_id="g",
                manifest_sha256="1" * 64,
            ))

    snapshot = Snapshots().pin_active(None).snapshot
    candidate = ObjectCandidate(
        candidate_id=canonical_hash(["candidate"]),
        domain="cti",
        scope_id="scope",
        snapshot=snapshot,
        target_object_uid="o",
        authorized_view=AuthorizedEvidenceView(
            evidence_uid="r",
            domain="cti",
            scope_id="scope",
            source_instances=("opencti",),
            policy=EvidencePolicyMetadata(),
        ),
        channel_scores=(
            ChannelScore(
                channel="lexical",
                rank=1,
                raw_score=1.0,
                score_kind="test",
            ),
        ),
        object_uid="o",
    )

    class Channel:
        name = "lexical"
        def search(self, plan, scope, snapshot, deadline):
            return ChannelResult(
                channel="lexical", status="ok", candidates=(candidate,)
            )

    class Reranker:
        def __init__(self): self.calls = 0
        def rerank(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("provider must not be called after freshness loss")

    reranker = Reranker()
    orchestrator = AdvancedRetrievalOrchestrator(
        policy=FreshnessPolicy(),
        snapshot_manager=Snapshots(),
        planner=DeterministicQueryPlanner(Adapter()),
        channels={"lexical": Channel()},
        reranker=reranker,
    )
    try:
        with pytest.raises(VisibilityExpired):
            orchestrator.retrieve(
                RetrievalRequest(query="general", corpus_id="opencti"),
                Principal(principal_id="u", source="trusted_local_cli"),
            )
    finally:
        orchestrator.close()
    assert reranker.calls == 0


def test_final_freshness_failure_prevents_response_serialization():
    from dataclasses import dataclass

    from packages.evidence.ids import canonical_hash
    from packages.evidence.policy import Principal
    from packages.evidence.schema import (
        AuthorizedEvidenceView,
        ChannelScore,
        EvidencePolicyMetadata,
        ObjectCandidate,
        RetrievalRequest,
        SnapshotRef,
    )
    from packages.retrieval.candidate import ChannelResult
    from packages.retrieval.orchestrator import AdvancedRetrievalOrchestrator
    from packages.retrieval.planner import DeterministicQueryPlanner

    class Adapter:
        domain = "cti"
        def parse_identifiers(self, query): return []
        def allowed_graph_patterns(self, hint): return []
        def infer_task_hint(self, query, identifiers): return "general"
        def requested_target_types(self, query, identifiers, task): return ()

    class FreshnessPolicy:
        def __init__(self): self.checks = 0
        def resolve_scope(self, principal, corpus):
            return ResolvedScope(
                principal_id=principal.principal_id,
                corpus_id=corpus,
                domain="cti", scope_id="scope", policy_version="v1",
                source_allowlist=frozenset({"opencti"}),
                allowed_destinations=frozenset({"caller"}),
            )
        def assert_scope_current(self, scope):
            self.checks += 1
            if self.checks >= 3:
                raise VisibilityExpired("corpus-access-denied")

    @dataclass
    class Handle:
        snapshot: SnapshotRef
        manifest: object = None
        def __enter__(self): return self
        def __exit__(self, *args): return False

    class Snapshots:
        def pin_active(self, scope):
            return Handle(SnapshotRef(
                domain="cti", scope_id="scope", snapshot_id="g",
                manifest_sha256="1" * 64,
            ))

    snapshot = Snapshots().pin_active(None).snapshot
    candidate = ObjectCandidate(
        candidate_id=canonical_hash(["candidate-final"]),
        domain="cti", scope_id="scope", snapshot=snapshot,
        target_object_uid="o",
        authorized_view=AuthorizedEvidenceView(
            evidence_uid="r", domain="cti", scope_id="scope",
            source_instances=("opencti",), policy=EvidencePolicyMetadata(),
        ),
        channel_scores=(
            ChannelScore(
                channel="lexical", rank=1, raw_score=1.0, score_kind="test"
            ),
        ),
        object_uid="o",
    )

    class Channel:
        name = "lexical"
        def search(self, plan, scope, snapshot, deadline):
            return ChannelResult(
                channel="lexical", status="ok", candidates=(candidate,)
            )

    class Packed:
        answer_context = "must-not-escape"
        packed_evidence = ("r",)
        tokens_used = 1
        omissions = ()
        def citation_records(self): return ()

    class Packer:
        def __init__(self): self.calls = 0
        def pack(self, *args, **kwargs):
            self.calls += 1
            return Packed()

    packer = Packer()
    orchestrator = AdvancedRetrievalOrchestrator(
        policy=FreshnessPolicy(),
        snapshot_manager=Snapshots(),
        planner=DeterministicQueryPlanner(Adapter()),
        channels={"lexical": Channel()},
        context_packer=packer,
    )
    try:
        with pytest.raises(VisibilityExpired):
            orchestrator.retrieve(
                RetrievalRequest(query="general", corpus_id="opencti"),
                Principal(principal_id="u", source="trusted_local_cli"),
            )
    finally:
        orchestrator.close()
    assert packer.calls == 1
