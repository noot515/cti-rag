from __future__ import annotations

import os
import sqlite3
import uuid

import pytest

from packages.evidence.ids import canonical_hash, canonical_json
from packages.evidence.policy import PolicyDecision, ResolvedScope
from packages.evidence.schema import SnapshotRef
from packages.indexing.manifests import GenerationManifest, GenerationMember, ProjectionSpec
from packages.indexing.vector_indexer import MilvusEndpointConfig, MilvusProjection, collection_name
from packages.retrieval.milvus import MilvusSearch, Pymilvus23Adapter
from packages.retrieval.providers import DeterministicFixtureEmbeddingProvider

pytestmark = pytest.mark.integration


class AllowPolicy:
    def authorize_evidence(self, view, scope, destination):
        return PolicyDecision(
            allowed=(view.domain == scope.domain and view.scope_id == scope.scope_id),
            reason="integration-public-fixture",
        )


class Store:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE generation_manifests(domain TEXT,scope_id TEXT,corpus_id TEXT,generation_id TEXT,manifest_sha256 TEXT,manifest_json TEXT);
            CREATE TABLE snapshot_membership(domain TEXT,scope_id TEXT,snapshot_id TEXT,evidence_kind TEXT,evidence_uid TEXT,revision_uid TEXT);
            CREATE TABLE chunks(domain TEXT,scope_id TEXT,chunk_uid TEXT,object_uid TEXT,object_revision_uid TEXT,payload_json TEXT);
            CREATE TABLE tombstones(domain TEXT,scope_id TEXT,evidence_uid TEXT,revision_uid TEXT);
            CREATE TABLE object_revisions(domain TEXT,scope_id TEXT,object_uid TEXT,revision_uid TEXT,lifecycle_state TEXT);
            """
        )


def _required_uri(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is not configured; real Milvus gate is not_run")
    return value


def _scope(scope_id: str) -> ResolvedScope:
    return ResolvedScope(
        principal_id="milvus-integration",
        corpus_id="fixture-cti",
        domain="cti",
        scope_id=scope_id,
        policy_version="integration",
        source_allowlist=frozenset({"fixture-public"}),
        allowed_destinations=frozenset({"caller", "local_generator"}),
    )


def _seed(store: Store, provider, scope_id: str):
    members = []
    for i, text in enumerate(("alpha CVE-2026-999999", "beta distractor"), 1):
        cuid = canonical_hash(["integration-chunk", scope_id, i])
        ouid = canonical_hash(["integration-object", scope_id, i])
        ruid = canonical_hash(["integration-revision", scope_id, i])
        payload = {
            "text": text,
            "policy": {
                "source_instances": ["fixture-public"],
                "marking_refs": [],
                "dissemination": [],
                "granular_selectors": [],
                "unresolved_markings": False,
            },
        }
        store.connection.execute(
            "INSERT INTO chunks VALUES(?,?,?,?,?,?)",
            ("cti", scope_id, cuid, ouid, ruid, canonical_json(payload)),
        )
        store.connection.execute(
            "INSERT INTO object_revisions VALUES(?,?,?,?,?)",
            ("cti", scope_id, ouid, ruid, "active"),
        )
        members.append(GenerationMember(kind="chunk", evidence_uid=cuid, revision_uid=cuid))
    manifest = GenerationManifest.create(
        domain="cti",
        scope_id=scope_id,
        corpus_id="fixture-cti",
        membership=members,
        projections=(
            ProjectionSpec(
                backend="dense",
                enabled=True,
                required=True,
                fingerprint=provider.fingerprint.digest,
            ),
        ),
        fingerprints={"embedding": provider.fingerprint.digest},
    )
    store.connection.execute(
        "INSERT INTO generation_manifests VALUES(?,?,?,?,?,?)",
        (
            "cti",
            scope_id,
            "fixture-cti",
            manifest.generation_id,
            manifest.manifest_sha256,
            canonical_json(manifest.model_dump(mode="json")),
        ),
    )
    for member in members:
        store.connection.execute(
            "INSERT INTO snapshot_membership VALUES(?,?,?,?,?,?)",
            (
                "cti",
                scope_id,
                manifest.generation_id,
                "chunk",
                member.evidence_uid,
                member.revision_uid,
            ),
        )
    return manifest


def _endpoint(uri: str, prefix: str) -> MilvusEndpointConfig:
    return MilvusEndpointConfig(
        uri=uri,
        deployment_id="advanced-integration",
        collection_prefix=prefix,
        expected_server_version="2.3.4",
        expected_client_version="2.3.7",
    )


def test_advanced_milvus_234_pymilvus_237_roundtrip():
    uri = _required_uri("ADVANCED_MILVUS_INTEGRATION_URI")
    pytest.importorskip("pymilvus")
    prefix = "adv_it_" + uuid.uuid4().hex[:10]
    endpoint = _endpoint(uri, prefix)
    client = Pymilvus23Adapter.connect(endpoint, alias="advanced-it")
    store = Store()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=16)
    scope_id = "integration-" + uuid.uuid4().hex[:12]
    manifest = _seed(store, provider, scope_id)
    writer = MilvusProjection(
        store,
        client=client,
        endpoint=endpoint,
        provider=provider,
        scope=_scope(scope_id),
        policy=AllowPolicy(),
        destination="local_generator",
    )
    receipt = writer.build(manifest)
    assert writer.verify(manifest, receipt)
    searcher = MilvusSearch(
        store, client=client, endpoint=endpoint, provider=provider, manifest=manifest
    )
    snapshot = SnapshotRef(
        domain=manifest.domain,
        scope_id=manifest.scope_id,
        snapshot_id=manifest.generation_id,
        manifest_sha256=manifest.manifest_sha256,
    )
    hits = searcher.search(
        "CVE-2026-999999",
        scope=_scope(scope_id),
        snapshot=snapshot,
        destination="local_generator",
        top_k=2,
    )
    assert hits


def test_legacy_endpoint_cannot_see_advanced_collection():
    advanced_uri = _required_uri("ADVANCED_MILVUS_INTEGRATION_URI")
    legacy_uri = _required_uri("LEGACY_MILVUS_INTEGRATION_URI")
    pytest.importorskip("pymilvus")
    from pymilvus import connections, utility

    prefix = "adv_iso_" + uuid.uuid4().hex[:10]
    endpoint = _endpoint(advanced_uri, prefix)
    client = Pymilvus23Adapter.connect(endpoint, alias="advanced-isolation")
    store = Store()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    scope_id = "isolation-" + uuid.uuid4().hex[:12]
    manifest = _seed(store, provider, scope_id)
    MilvusProjection(
        store,
        client=client,
        endpoint=endpoint,
        provider=provider,
        scope=_scope(scope_id),
        policy=AllowPolicy(),
        destination="local_generator",
    ).build(manifest)
    advanced_collection = collection_name(endpoint, manifest)

    connections.connect(alias="legacy-isolation-check", uri=legacy_uri)
    assert not utility.has_collection(advanced_collection, using="legacy-isolation-check")
    assert not hasattr(Pymilvus23Adapter, "drop_collection")
