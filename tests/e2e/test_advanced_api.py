from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from packages.evidence.access import (
    CorpusAccessStore,
    CorpusGrant,
    CorpusRegistrationManifest,
)
from packages.evidence.config import AdvancedRagConfig
from packages.evidence.policy import TrustedPrincipal
from packages.evidence.schema import RetrievalResult, SnapshotRef
from packages.retrieval.orchestrator import RetrievalUnavailable
from rag.api.advanced_app import create_fixture_app
from rag.api.routers.advanced_retrieval_api import AdvancedApiRuntime


H = "b" * 64


def admin():
    return TrustedPrincipal(
        principal_id="operator",
        principal_namespace="local-admin",
        source="trusted_local_cli",
        capabilities=frozenset({"corpus:register"}),
    )


def registered_store(path):
    store = CorpusAccessStore(path)
    store.register_corpus(
        CorpusRegistrationManifest(
            corpus_key="fixture-cti",
            domain="cti",
            scope_id="public-fixture",
            active_catalog_id="fixture-generation",
            policy_version="fixture-policy",
            source_allowlist=frozenset({"fixture-public"}),
            allowed_destinations=frozenset({"caller", "debug_trace"}),
            grants=(CorpusGrant(principal_namespace="user.id", principal_id="11"),),
        ),
        actor=admin(),
    )
    return store


class StubOrchestrator:
    def __init__(self, *, status="ok", fail=False):
        self.status = status
        self.fail = fail
        self.calls = 0

    def retrieve(self, request, principal):
        self.calls += 1
        if self.fail:
            raise RetrievalUnavailable("all channels unavailable")
        return RetrievalResult(
            retrieval_run_id="fixture-run",
            domain="cti",
            snapshot=SnapshotRef(
                domain="cti",
                scope_id="public-fixture",
                snapshot_id="fixture-generation",
                manifest_sha256=H,
            ),
            status=self.status,
            answer_context="[CTI-001]\nUntrusted evidence: fixture",
            citations=(),
            authorized_trace=(
                "channel=exact;status=ok;count=1;truncated=false",
                "channel=dense;status=timeout;count=0;truncated=true",
            ),
            truncated=self.status == "partial",
            timings_ms={"exact": 1.0, "dense": 3.0, "total": 4.0},
            model_fingerprints={"embedding": "fixture-hash-v1"},
        )


def config():
    return AdvancedRagConfig(enabled=True, profile="fixture")


def make_client(store, orchestrator, *, user_id=11, capabilities=() , finalizer=None):
    async def user():
        return SimpleNamespace(id=user_id, user_id=999999, is_active=True)

    runtime = AdvancedApiRuntime(
        orchestrator=orchestrator,
        finalize_result=finalizer or (lambda result, _context: result),
        authorize_debug_candidate=lambda _candidate, _context: True,
    )
    app = create_fixture_app(
        config=config(),
        runtime_provider=lambda _context: runtime,
        access_store_provider=lambda: store,
        authenticated_user_dependency=user,
        capability_resolver=lambda _user: capabilities,
    )
    return TestClient(app)


def test_successful_fixture_and_partial_status(tmp_path):
    store = registered_store(tmp_path / "access.sqlite")
    response = make_client(store, StubOrchestrator(status="partial")).post(
        "/chat/advanced-retrieval",
        json={"query": "Map CVE-2026-999999 to CWE", "db_id": "fixture-cti"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["domain"] == "cti"
    assert payload["snapshot_id"] == "fixture-generation"
    assert payload["channel_status"]["dense"] == "timeout"
    assert payload["degraded_channels"] == ["dense"]
    assert "answer" not in payload
    store.close()


def test_successful_empty_is_no_evidence_not_503(tmp_path):
    store = registered_store(tmp_path / "access.sqlite")
    response = make_client(store, StubOrchestrator(status="no_evidence")).post(
        "/chat/advanced-retrieval",
        json={"query": "unknown", "db_id": "fixture-cti"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "no_evidence"
    store.close()


def test_cross_tenant_denied_before_backend_call(tmp_path):
    store = registered_store(tmp_path / "access.sqlite")
    orchestrator = StubOrchestrator()
    response = make_client(store, orchestrator, user_id=12).post(
        "/chat/advanced-retrieval",
        json={"query": "x", "db_id": "fixture-cti"},
    )
    assert response.status_code == 403
    assert orchestrator.calls == 0
    store.close()


def test_all_channels_unavailable_is_503_without_legacy_fallback(tmp_path):
    store = registered_store(tmp_path / "access.sqlite")
    response = make_client(store, StubOrchestrator(fail=True)).post(
        "/chat/advanced-retrieval",
        json={"query": "x", "db_id": "fixture-cti"},
    )
    assert response.status_code == 503
    store.close()


def test_withdrawal_finalizer_runs_before_serialization(tmp_path):
    store = registered_store(tmp_path / "access.sqlite")
    seen = {"called": False}

    def finalizer(result, _context):
        seen["called"] = True
        return result.model_copy(update={"answer_context": "", "citations": (), "status": "no_evidence"})

    response = make_client(
        store,
        StubOrchestrator(),
        finalizer=finalizer,
    ).post(
        "/chat/advanced-retrieval",
        json={"query": "x", "db_id": "fixture-cti"},
    )
    assert response.status_code == 200
    assert seen["called"] is True
    assert response.json()["answer_context"] == ""
    assert response.json()["status"] == "no_evidence"
    store.close()


def test_full_mode_requires_and_accepts_server_owned_debug_capability(tmp_path):
    store = registered_store(tmp_path / "access.sqlite")
    denied = make_client(store, StubOrchestrator()).post(
        "/chat/advanced-retrieval",
        json={"query": "x", "db_id": "fixture-cti", "response_mode": "full"},
    )
    assert denied.status_code == 403

    allowed = make_client(
        store,
        StubOrchestrator(),
        capabilities=("evidence:debug",),
    ).post(
        "/chat/advanced-retrieval",
        json={"query": "x", "db_id": "fixture-cti", "response_mode": "full"},
    )
    assert allowed.status_code == 200
    assert "candidates" in allowed.json()
    store.close()
