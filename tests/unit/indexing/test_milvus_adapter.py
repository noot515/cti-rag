from __future__ import annotations

import math
import os
import re
import sqlite3
from pathlib import Path
import subprocess
import sys
import time

import pytest

from packages.evidence.ids import canonical_hash, canonical_json
from packages.evidence.policy import PolicyDecision, ResolvedScope
from packages.evidence.schema import SnapshotRef
from packages.indexing.manifests import GenerationManifest, GenerationMember, ProjectionSpec
from packages.indexing.vector_indexer import (
    MilvusEndpointConfig,
    MilvusFieldOverflow,
    MilvusProjection,
    MilvusSchemaMismatch,
    MilvusVisibilityError,
    collection_name,
)
from packages.retrieval.milvus import MilvusChannel, MilvusSearch, Pymilvus23Adapter
from packages.retrieval.providers import DeterministicFixtureEmbeddingProvider


class AllowPolicy:
    def authorize_evidence(self, view, scope, destination):
        return PolicyDecision(
            allowed=(view.domain == scope.domain and view.scope_id == scope.scope_id),
            reason="allow",
        )


class FakeStore:
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


class FakeMilvus:
    def __init__(self, *, visibility=True):
        self.collections = {}
        self.visibility = visibility
        self.create_calls = 0
        self.upsert_calls = 0
        self.drop_calls = 0
        self.last_search_filter = None
        self.last_search_limit = None
        self.fail_search = False

    def server_version(self):
        return "2.3.4"

    def collection_exists(self, name):
        return name in self.collections

    def create_collection(self, spec):
        assert spec.collection_name not in self.collections
        self.create_calls += 1
        self.collections[spec.collection_name] = {
            "spec": spec,
            "records": {},
            "loaded": False,
        }

    def describe_collection(self, name):
        spec = self.collections[name]["spec"]
        return {
            "schema_fingerprint": spec.schema_fingerprint,
            "metric": spec.metric,
        }

    def upsert(self, name, records):
        self.upsert_calls += 1
        for record in records:
            self.collections[name]["records"][record["chunk_uid"]] = dict(record)
        return len(records)

    def flush(self, name):
        pass

    def load(self, name):
        self.collections[name]["loaded"] = True

    @staticmethod
    def _conditions(expr):
        return dict(re.findall(r'(\w+) == "((?:\\.|[^"])*)"', expr))

    def _filtered(self, name, expr):
        wanted = self._conditions(expr)
        rows = []
        for record in self.collections[name]["records"].values():
            if all(
                str(record.get(key))
                == value.replace('\\"', '"').replace('\\\\', '\\')
                for key, value in wanted.items()
            ):
                rows.append(dict(record))
        return rows

    def query(self, name, *, filter_expr, output_fields, limit):
        if not self.visibility:
            return []
        return [
            {key: row.get(key) for key in output_fields}
            for row in self._filtered(name, filter_expr)[:limit]
        ]

    def search(self, name, *, vector, filter_expr, limit, metric, output_fields):
        if self.fail_search:
            raise RuntimeError("service down")
        self.last_search_filter = filter_expr
        self.last_search_limit = limit
        rows = []
        for row in self._filtered(name, filter_expr):
            stored = row["vector"]
            if metric in {"COSINE", "IP"}:
                score = sum(a * b for a, b in zip(vector, stored))
                if metric == "COSINE":
                    qn = math.sqrt(sum(a * a for a in vector))
                    dn = math.sqrt(sum(a * a for a in stored))
                    score = score / (qn * dn)
            else:
                score = -sum((a - b) ** 2 for a, b in zip(vector, stored))
            out = {key: row.get(key) for key in output_fields}
            out["score"] = score
            rows.append(out)
        rows.sort(key=lambda x: (-x["score"], x["chunk_uid"]))
        return rows[:limit]


def setup(store, provider, *, scope_id="scope-a", text_prefix="alpha"):
    members = []
    chunks = []
    for idx, text in enumerate((f"{text_prefix} one", f"{text_prefix} two"), 1):
        cuid = canonical_hash(["chunk", scope_id, idx])
        ouid = canonical_hash(["object", scope_id, idx])
        ruid = canonical_hash(["revision", scope_id, idx])
        payload = {"text": text, "policy": {"source_instances": ["fixture-public"]}}
        store.connection.execute(
            "INSERT INTO chunks VALUES(?,?,?,?,?,?)",
            ("cti", scope_id, cuid, ouid, ruid, canonical_json(payload)),
        )
        store.connection.execute(
            "INSERT INTO object_revisions VALUES(?,?,?,?,?)",
            ("cti", scope_id, ouid, ruid, "active"),
        )
        members.append(GenerationMember(kind="chunk", evidence_uid=cuid, revision_uid=cuid))
        chunks.append((cuid, ouid, ruid))
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
    for cuid, _, _ in chunks:
        store.connection.execute(
            "INSERT INTO snapshot_membership VALUES(?,?,?,?,?,?)",
            ("cti", scope_id, manifest.generation_id, "chunk", cuid, cuid),
        )
    return manifest, chunks


def resolved(scope_id="scope-a"):
    return ResolvedScope(
        principal_id="test",
        corpus_id="fixture-cti",
        domain="cti",
        scope_id=scope_id,
        policy_version="test",
        source_allowlist=frozenset({"fixture-public"}),
        allowed_destinations=frozenset({"caller", "local_generator"}),
    )


def snap(manifest):
    return SnapshotRef(
        domain=manifest.domain,
        scope_id=manifest.scope_id,
        snapshot_id=manifest.generation_id,
        manifest_sha256=manifest.manifest_sha256,
    )


def endpoint():
    return MilvusEndpointConfig(
        uri="http://127.0.0.1:19531",
        deployment_id="advanced-test",
        collection_prefix="adv_test",
    )


def projection(store, client, provider, manifest):
    return MilvusProjection(
        store,
        client=client,
        endpoint=endpoint(),
        provider=provider,
        scope=resolved(manifest.scope_id),
        policy=AllowPolicy(),
        destination="local_generator",
    )


def test_schema_manual_string_pk_upsert_and_visibility_contracts():
    store = FakeStore()
    client = FakeMilvus()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    manifest, chunks = setup(store, provider)
    writer = projection(store, client, provider, manifest)
    receipt = writer.build(manifest)
    name = collection_name(endpoint(), manifest)
    spec = client.collections[name]["spec"]
    primary = [field for field in spec.fields if field.primary]
    assert [(field.name, field.kind, field.max_length) for field in primary] == [
        ("chunk_uid", "VARCHAR", 64)
    ]
    vector = next(field for field in spec.fields if field.name == "vector")
    assert vector.dimension == 8
    assert receipt.visibility_verified
    assert writer.verify(manifest, receipt)
    assert set(client.collections[name]["records"]) == {item[0] for item in chunks}


def test_repeated_ingestion_is_idempotent_and_never_recreates_collection():
    store = FakeStore()
    client = FakeMilvus()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    manifest, _ = setup(store, provider)
    writer = projection(store, client, provider, manifest)
    first = writer.build(manifest)
    second = writer.build(manifest)
    assert first.artifact_sha256 == second.artifact_sha256
    assert client.create_calls == 1
    assert client.upsert_calls == 2
    assert client.drop_calls == 0


def test_two_scopes_use_different_generation_collections():
    store = FakeStore()
    client = FakeMilvus()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    a, _ = setup(store, provider, scope_id="scope-a")
    b, _ = setup(store, provider, scope_id="scope-b")
    projection(store, client, provider, a).build(a)
    projection(store, client, provider, b).build(b)
    assert collection_name(endpoint(), a) != collection_name(endpoint(), b)
    assert len(client.collections) == 2


def test_search_prefilters_scope_generation_and_authoritative_revision_recheck():
    store = FakeStore()
    client = FakeMilvus()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    manifest, chunks = setup(store, provider)
    projection(store, client, provider, manifest).build(manifest)
    name = collection_name(endpoint(), manifest)
    client.collections[name]["records"][chunks[0][0]]["object_revision_uid"] = "f" * 64
    searcher = MilvusSearch(
        store, client=client, endpoint=endpoint(), provider=provider, manifest=manifest
    )
    hits = searcher.search(
        "alpha",
        scope=resolved(),
        snapshot=snap(manifest),
        destination="local_generator",
        top_k=2,
        overfetch_factor=4,
    )
    assert chunks[0][0] not in {hit.logical_uid for hit in hits}
    assert 'scope_id == "scope-a"' in client.last_search_filter
    assert f'generation_id == "{manifest.generation_id}"' in client.last_search_filter
    assert client.last_search_limit == 8


def test_byte_overflow_fails_before_collection_side_effect():
    store = FakeStore()
    client = FakeMilvus()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    too_long_scope = "x" * 300
    manifest, _ = setup(store, provider, scope_id=too_long_scope)
    with pytest.raises(MilvusFieldOverflow):
        projection(store, client, provider, manifest).build(manifest)
    assert client.create_calls == 0


def test_wrong_embedding_fingerprint_rejected_without_backend_write():
    store = FakeStore()
    client = FakeMilvus()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    manifest, _ = setup(store, provider)
    wrong = DeterministicFixtureEmbeddingProvider(dimensions=8, revision="fixture-v2")
    with pytest.raises(Exception, match="reindex"):
        projection(store, client, wrong, manifest).build(manifest)
    assert client.create_calls == 0


def test_visibility_lag_fails_readiness_and_existing_collection_is_not_dropped():
    store = FakeStore()
    client = FakeMilvus(visibility=False)
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    manifest, _ = setup(store, provider)
    with pytest.raises(MilvusVisibilityError):
        projection(store, client, provider, manifest).build(manifest)
    assert client.create_calls == 1
    assert client.drop_calls == 0


def test_incompatible_existing_collection_fails_without_recreate():
    store = FakeStore()
    client = FakeMilvus()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    manifest, _ = setup(store, provider)
    name = collection_name(endpoint(), manifest)

    class BadSpec:
        schema_fingerprint = "bad"
        collection_name = name
        metric = "L2"
        fields = ()

    client.collections[name] = {"spec": BadSpec(), "records": {}, "loaded": False}
    with pytest.raises(MilvusSchemaMismatch):
        projection(store, client, provider, manifest).build(manifest)
    assert client.create_calls == 0
    assert client.drop_calls == 0


@pytest.mark.asyncio
async def test_query_outage_returns_unavailable_channel_status():
    store = FakeStore()
    client = FakeMilvus()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    manifest, _ = setup(store, provider)
    projection(store, client, provider, manifest).build(manifest)
    client.fail_search = True
    searcher = MilvusSearch(
        store, client=client, endpoint=endpoint(), provider=provider, manifest=manifest
    )
    channel = MilvusChannel(
        searcher, policy=AllowPolicy(), destination="local_generator", top_k=2
    )
    result = await channel.search(
        "alpha", resolved(), snap(manifest), time.monotonic() + 10.0
    )
    assert result.status == "error"
    assert result.reason == "backend-unavailable"


def test_advanced_milvus_import_is_pymilvus_inert_in_fresh_process():
    root = Path(__file__).resolve().parents[3]
    code = (
        "import sys; before='pymilvus' in sys.modules; "
        "import packages.indexing.vector_indexer, packages.retrieval.milvus; "
        "print(int(('pymilvus' in sys.modules) and not before))"
    )
    env = {**os.environ, "PYTHONPATH": str(root)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == "0"


def test_endpoint_contract_rejects_legacy_identity_and_adapter_exposes_no_drop_api():
    with pytest.raises(ValueError):
        MilvusEndpointConfig(
            uri="http://127.0.0.1:19530",
            deployment_id="legacy-milvus",
            collection_prefix="kb_default",
        )
    assert not hasattr(Pymilvus23Adapter, "drop_collection")


def test_server_version_mismatch_fails_before_collection_write():
    store = FakeStore()
    client = FakeMilvus()
    client.server_version = lambda: "2.4.0"
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    manifest, _ = setup(store, provider)
    with pytest.raises(Exception, match="server version mismatch"):
        projection(store, client, provider, manifest).build(manifest)
    assert client.create_calls == 0
