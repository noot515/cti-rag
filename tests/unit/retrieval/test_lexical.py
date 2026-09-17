from __future__ import annotations

from hashlib import sha256
import json

import pytest

from packages.domains.cti import CtiDomainAdapter, CtiChunk
from packages.evidence.ids import chunk_uid
from packages.evidence.policy import PolicyDenied, Principal, PublicFixturePolicy
from packages.evidence.store import EvidenceStore
from packages.indexing.chunker import ChunkingConfig, DeterministicTokenizer, chunk_objects
from packages.indexing.lexical_indexer import LexicalProjectionWriter
from packages.indexing.manifests import GenerationManifest, GenerationMember, ProjectionSpec
from packages.indexing.orchestrator import PublicationOrchestrator
from packages.retrieval.lexical import LexicalIndex, LexicalIndexError

from tests.unit.indexing._helpers import batch_and_raw


def _with_chunks(batch):
    tokenizer = DeterministicTokenizer()
    chunks = chunk_objects(
        batch.objects,
        serialization_hints=CtiDomainAdapter().field_serialization_hints(),
        tokenizer=tokenizer,
        config=ChunkingConfig(),
        chunk_class=CtiChunk,
    )
    return batch.model_copy(update={"chunks": chunks}), tokenizer


def _manifest(batch, writer, tokenizer):
    members = [GenerationMember(kind="object", evidence_uid=x.uid, revision_uid=x.revision_uid) for x in batch.objects]
    members += [GenerationMember(kind="relation", evidence_uid=x.uid, revision_uid=x.revision_uid) for x in batch.relations]
    members += [GenerationMember(kind="chunk", evidence_uid=x.uid, revision_uid=x.uid) for x in batch.chunks]
    return GenerationManifest.create(
        domain=batch.domain,
        scope_id=batch.scope_id,
        corpus_id="fixture-cti",
        membership=members,
        projections=(
            ProjectionSpec(backend="exact", enabled=False, required=False, fingerprint="not-configured"),
            ProjectionSpec(backend="lexical", enabled=True, required=True, fingerprint=writer.fingerprint),
            ProjectionSpec(backend="dense", enabled=False, required=False, fingerprint="not-configured"),
            ProjectionSpec(backend="graph", enabled=False, required=False, fingerprint="not-configured"),
        ),
        fingerprints={"tokenizer": tokenizer.fingerprint, "lexical": writer.fingerprint},
    )


def _scope_snapshot(manifest):
    policy = PublicFixturePolicy.trusted(
        corpus_id="fixture-cti", scope_id="public-fixture", source_allowlist=frozenset({"fixture-public"})
    )
    scope = policy.resolve_scope(Principal(principal_id="test", source="trusted_local_cli"), "fixture-cti")
    snapshot = __import__("packages.evidence.schema", fromlist=["SnapshotRef"]).SnapshotRef(
        domain=manifest.domain, scope_id=manifest.scope_id, snapshot_id=manifest.generation_id, manifest_sha256=manifest.manifest_sha256
    )
    return policy, scope, snapshot


def _publish(tmp_path, *, name_suffix=""):
    batch, raw = batch_and_raw(name_suffix=name_suffix)
    batch, tokenizer = _with_chunks(batch)
    store = EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw")
    store.persist_batch(batch, raw_payloads=raw)
    writer = LexicalProjectionWriter(store, tmp_path / "indexes", tokenizer=tokenizer)
    manifest = _manifest(batch, writer, tokenizer)
    PublicationOrchestrator.trusted(store, [writer]).publish(manifest)
    policy, scope, snapshot = _scope_snapshot(manifest)
    path = LexicalIndex.path_for(tmp_path / "indexes", domain="cti", scope_id="public-fixture", generation_id=manifest.generation_id)
    return store, batch, manifest, policy, scope, snapshot, path


def test_full_corpus_bm25_finds_description_only_term_and_excludes_zero_scores(tmp_path):
    store, batch, manifest, policy, scope, snapshot, path = _publish(tmp_path)
    try:
        index = LexicalIndex.open(store, path=path)
        hits = index.search("distractor", scope=scope, snapshot=snapshot)
        assert hits
        assert all(hit.raw_score > 0 for hit in hits)
        assert index.search("zzzz-not-present-anywhere", scope=scope, snapshot=snapshot) == ()
        assert index.search("", scope=scope, snapshot=snapshot) == ()
    finally:
        store.close()


def test_bm25_ranking_survives_restart_without_refitting(tmp_path):
    store, batch, manifest, policy, scope, snapshot, path = _publish(tmp_path)
    before = LexicalIndex.open(store, path=path).search("synthetic", scope=scope, snapshot=snapshot)
    db, raw_root = store.catalog_path, store.raw_store.root
    store.close()
    with EvidenceStore(db, raw_root) as reopened:
        after = LexicalIndex.open(reopened, path=path).search("synthetic", scope=scope, snapshot=snapshot)
        assert [(x.logical_uid, x.raw_score) for x in before] == [(x.logical_uid, x.raw_score) for x in after]


def test_corrupt_persistent_index_refuses_open(tmp_path):
    store, batch, manifest, policy, scope, snapshot, path = _publish(tmp_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["documents"][0]["content_hash"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(LexicalIndexError):
            LexicalIndex.open(store, path=path)
    finally:
        store.close()


def test_unauthorized_chunk_is_never_hydrated(tmp_path):
    batch, raw = batch_and_raw()
    tokenizer = DeterministicTokenizer()
    obj = batch.objects[0]
    text = "restricted lexical sentinel"
    content_hash = sha256(text.encode("utf-8")).hexdigest()
    policy_meta = obj.policy.model_copy(update={"dissemination": ("tlp:amber",)})
    uid = chunk_uid(
        object_id=obj.uid,
        object_revision_id=obj.revision_uid,
        chunker_fingerprint="restricted-fixture-v1",
        section_path="description",
        ordinal=0,
        content_hash=content_hash,
    )
    restricted = CtiChunk(
        uid=uid,
        object_uid=obj.uid,
        object_revision_uid=obj.revision_uid,
        scope_id=obj.scope_id,
        chunker_fingerprint="restricted-fixture-v1",
        section_path="description",
        ordinal=0,
        text=text,
        content_hash=content_hash,
        token_count=len(tokenizer.tokens(text)),
        tokenizer_fingerprint=tokenizer.fingerprint,
        source_refs=obj.source_refs,
        policy=policy_meta,
    )
    batch = batch.model_copy(update={"chunks": (restricted,)})
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        store.persist_batch(batch, raw_payloads=raw)
        writer = LexicalProjectionWriter(store, tmp_path / "indexes", tokenizer=tokenizer)
        manifest = _manifest(batch, writer, tokenizer)
        PublicationOrchestrator.trusted(store, [writer]).publish(manifest)
        policy, scope, snapshot = _scope_snapshot(manifest)
        index = LexicalIndex.open(
            store,
            path=LexicalIndex.path_for(tmp_path / "indexes", domain="cti", scope_id="public-fixture", generation_id=manifest.generation_id),
            tokenizer=tokenizer,
        )
        hit = index.search("restricted", scope=scope, snapshot=snapshot)[0]
        with pytest.raises(PolicyDenied):
            index.hydrate(hit, scope=scope, snapshot=snapshot, policy=policy)
