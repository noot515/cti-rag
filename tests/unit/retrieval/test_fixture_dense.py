from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from packages.evidence.ids import canonical_hash, canonical_json
from packages.evidence.policy import PolicyDecision, ResolvedScope
from packages.evidence.schema import SnapshotRef
from packages.indexing.manifests import GenerationManifest, GenerationMember, ProjectionSpec
from packages.retrieval.dense import DenseFingerprintMismatch, DenseIndex, DenseProjectionWriter
from packages.retrieval.providers import DeterministicFixtureEmbeddingProvider


class AllowPolicy:
    def authorize_evidence(self, view, scope, destination):
        return PolicyDecision(
            allowed=(view.domain == scope.domain and view.scope_id == scope.scope_id),
            reason="fixture",
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


def setup_generation(store: FakeStore, provider, *, scope_id="scope-a"):
    chunks = []
    members = []
    for i, text in enumerate(("alpha CVE-2026-999999 weakness", "beta unrelated distractor"), 1):
        cuid = canonical_hash(["chunk", scope_id, i])
        ouid = canonical_hash(["object", scope_id, i])
        ruid = canonical_hash(["revision", scope_id, i])
        payload = {
            "text": text,
            "policy": {"source_instances": ["fixture-public"]},
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
        chunks.append((cuid, ouid, ruid))
    manifest = GenerationManifest.create(
        domain="cti",
        scope_id=scope_id,
        corpus_id="fixture-cti",
        membership=members,
        projections=(ProjectionSpec(backend="dense", enabled=True, required=True, fingerprint=provider.fingerprint.digest),),
        fingerprints={"embedding": provider.fingerprint.digest},
    )
    store.connection.execute(
        "INSERT INTO generation_manifests VALUES(?,?,?,?,?,?)",
        ("cti", scope_id, "fixture-cti", manifest.generation_id, manifest.manifest_sha256, canonical_json(manifest.model_dump(mode="json"))),
    )
    for cuid, _, _ in chunks:
        store.connection.execute(
            "INSERT INTO snapshot_membership VALUES(?,?,?,?,?,?)",
            ("cti", scope_id, manifest.generation_id, "chunk", cuid, cuid),
        )
    return manifest, chunks


def scope(scope_id="scope-a"):
    return ResolvedScope(
        principal_id="test",
        corpus_id="fixture-cti",
        domain="cti",
        scope_id=scope_id,
        policy_version="test",
        source_allowlist=frozenset({"fixture-public"}),
        allowed_destinations=frozenset({"caller", "local_generator"}),
    )


def snapshot(manifest):
    return SnapshotRef(
        domain=manifest.domain,
        scope_id=manifest.scope_id,
        snapshot_id=manifest.generation_id,
        manifest_sha256=manifest.manifest_sha256,
    )


def test_fixture_dense_build_reopen_and_ranking_are_stable(tmp_path: Path):
    store = FakeStore()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=16)
    manifest, _ = setup_generation(store, provider)
    index = DenseIndex.build(
        store,
        root=tmp_path,
        manifest=manifest,
        provider=provider,
        scope=scope(),
        policy=AllowPolicy(),
        destination="local_generator",
    )
    hits1 = index.search(
        "CVE-2026-999999 weakness",
        provider=provider,
        scope=scope(),
        snapshot=snapshot(manifest),
        destination="local_generator",
        top_k=2,
    )
    reopened = DenseIndex.open(store, path=index.path, provider=provider)
    hits2 = reopened.search(
        "CVE-2026-999999 weakness",
        provider=provider,
        scope=scope(),
        snapshot=snapshot(manifest),
        destination="local_generator",
        top_k=2,
    )
    assert [(h.logical_uid, h.raw_score) for h in hits1] == [(h.logical_uid, h.raw_score) for h in hits2]
    assert reopened.embedding_fingerprint_digest == provider.fingerprint.digest


def test_dense_scope_snapshot_and_provider_fingerprint_are_enforced(tmp_path: Path):
    store = FakeStore()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    manifest, _ = setup_generation(store, provider)
    index = DenseIndex.build(
        store,
        root=tmp_path,
        manifest=manifest,
        provider=provider,
        scope=scope(),
        policy=AllowPolicy(),
        destination="local_generator",
    )
    with pytest.raises(Exception, match="scope"):
        index.search(
            "alpha",
            provider=provider,
            scope=scope("wrong-scope"),
            snapshot=snapshot(manifest),
            destination="local_generator",
        )
    wrong = DeterministicFixtureEmbeddingProvider(dimensions=8, revision="fixture-v2")
    with pytest.raises(DenseFingerprintMismatch, match="reindex"):
        DenseIndex.open(store, path=index.path, provider=wrong)


def test_dense_projection_writer_receipt_binds_provider_fingerprint(tmp_path: Path):
    store = FakeStore()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    manifest, _ = setup_generation(store, provider)
    writer = DenseProjectionWriter(
        store,
        tmp_path,
        provider=provider,
        scope=scope(),
        policy=AllowPolicy(),
    )
    receipt = writer.build(manifest)
    assert receipt.backend == "dense"
    assert receipt.fingerprint == provider.fingerprint.digest
    assert writer.verify(manifest, receipt)


def test_same_dimension_wrong_model_is_rejected_at_manifest_boundary(tmp_path: Path):
    store = FakeStore()
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    manifest, _ = setup_generation(store, provider)
    wrong = DeterministicFixtureEmbeddingProvider(dimensions=8, revision="other-revision")
    writer = DenseProjectionWriter(store, tmp_path, provider=wrong, scope=scope(), policy=AllowPolicy())
    with pytest.raises(DenseFingerprintMismatch):
        writer.build(manifest)


def test_dense_build_accounts_for_policy_excluded_chunks_without_provider_egress(tmp_path: Path):
    store = FakeStore()

    class RecordingProvider(DeterministicFixtureEmbeddingProvider):
        def __init__(self):
            super().__init__(dimensions=8)
            self.document_item_ids = ()

        def encode_documents(self, items, *, destination, deadline=None, cancelled=None):
            self.document_item_ids = tuple(item.item_id for item in items)
            return super().encode_documents(
                items,
                destination=destination,
                deadline=deadline,
                cancelled=cancelled,
            )

    class DenySecondPolicy:
        def __init__(self, denied_uid: str):
            self.denied_uid = denied_uid

        def authorize_evidence(self, view, scope, destination):
            allowed = view.evidence_uid != self.denied_uid
            return PolicyDecision(
                allowed=allowed,
                reason="fixture" if allowed else "policy-excluded",
            )

    provider = RecordingProvider()
    manifest, chunks = setup_generation(store, provider)
    denied_uid = chunks[1][0]
    index = DenseIndex.build(
        store,
        root=tmp_path,
        manifest=manifest,
        provider=provider,
        scope=scope(),
        policy=DenySecondPolicy(denied_uid),
        destination="local_generator",
    )

    assert denied_uid not in provider.document_item_ids
    assert {entry["chunk_uid"] for entry in index.entries} == {chunks[0][0]}
    assert index.policy_excluded_chunk_uids == (denied_uid,)

    reopened = DenseIndex.open(store, path=index.path, provider=provider)
    assert reopened.policy_excluded_chunk_uids == (denied_uid,)
