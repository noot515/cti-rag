from __future__ import annotations

from types import SimpleNamespace
import subprocess
import sys

from fastapi.testclient import TestClient

from packages.evidence.access import (
    CorpusAccessStore,
    CorpusGrant,
    CorpusRegistrationManifest,
)
from packages.evidence.config import AdvancedRagConfig
from packages.evidence.policy import TrustedPrincipal
from packages.evidence.schema import RetrievalResult, SnapshotRef
from rag.api.advanced_app import create_advanced_app
from rag.api.routers.advanced_retrieval_api import AdvancedApiRuntime, AdvancedRetrievalBody


H = "a" * 64


def _admin():
    return TrustedPrincipal(
        principal_id="operator",
        principal_namespace="local-admin",
        source="trusted_local_cli",
        capabilities=frozenset({"corpus:register"}),
    )


def _store(path):
    store = CorpusAccessStore(path)
    store.register_corpus(
        CorpusRegistrationManifest(
            corpus_key="fixture-cti",
            domain="cti",
            scope_id="public-fixture",
            active_catalog_id="fixture",
            policy_version="p1",
            source_allowlist=frozenset({"fixture-public"}),
            allowed_destinations=frozenset({"caller", "debug_trace"}),
            grants=(CorpusGrant(principal_namespace="user.id", principal_id="11"),),
        ),
        actor=_admin(),
    )
    return store


class FakeOrchestrator:
    def __init__(self, status="ok"):
        self.status = status
        self.calls = 0

    def retrieve(self, request, principal):
        self.calls += 1
        return RetrievalResult(
            retrieval_run_id="run-1",
            domain="cti",
            snapshot=SnapshotRef(
                domain="cti",
                scope_id="public-fixture",
                snapshot_id="generation-1",
                manifest_sha256=H,
            ),
            status=self.status,
            answer_context="[CTI-001] fixture evidence",
            citations=(),
            authorized_trace=("channel=exact;status=ok;count=1;truncated=false",),
            timings_ms={"total": 1.0},
        )


def _config(enabled=True):
    return AdvancedRagConfig(enabled=enabled, profile="fixture")


def test_body_rejects_unknown_authority_fields_and_web_search():
    assert AdvancedRetrievalBody(query="x", db_id="fixture-cti").web_search is False
    for payload in (
        {"query": "x", "db_id": "fixture-cti", "principal_id": "11"},
        {"query": "x", "db_id": "fixture-cti", "policy": "allow-all"},
        {"query": "x", "db_id": "fixture-cti", "web_search": True},
    ):
        try:
            AdvancedRetrievalBody.model_validate(payload)
        except Exception:
            pass
        else:
            raise AssertionError("invalid advanced authority/filter field was accepted")


def test_disabled_route_is_absent(tmp_path):
    store = _store(tmp_path / "access.sqlite")
    async def user():
        return SimpleNamespace(id=11, user_id=999, is_active=True)
    app = create_advanced_app(
        config=_config(False),
        runtime_provider=lambda _: AdvancedApiRuntime(FakeOrchestrator(), lambda r, _c: r),
        access_store_provider=lambda: store,
        authenticated_user_dependency=user,
    )
    response = TestClient(app).post(
        "/chat/advanced-retrieval",
        json={"query": "x", "db_id": "fixture-cti"},
    )
    assert response.status_code == 404
    store.close()


def test_full_mode_requires_independent_debug_capability(tmp_path):
    store = _store(tmp_path / "access.sqlite")
    orchestrator = FakeOrchestrator()
    async def user():
        return SimpleNamespace(id=11, user_id=999, is_active=True)
    app = create_advanced_app(
        config=_config(True),
        runtime_provider=lambda _: AdvancedApiRuntime(orchestrator, lambda r, _c: r),
        access_store_provider=lambda: store,
        authenticated_user_dependency=user,
    )
    response = TestClient(app).post(
        "/chat/advanced-retrieval",
        json={"query": "x", "db_id": "fixture-cti", "response_mode": "full"},
    )
    assert response.status_code == 403
    assert orchestrator.calls == 0
    store.close()


def test_fresh_process_import_does_not_load_legacy_service_routers():
    code = r'''
import sys
import rag.api.advanced_app
for forbidden in (
    "rag.api.routers.chat_api",
    "rag.api.routers.data_api",
    "rag.api.routers.graph_api",
    "rag.api.routers.token_api",
    "packages.manager.db_manager",
):
    assert forbidden not in sys.modules, forbidden
'''
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
