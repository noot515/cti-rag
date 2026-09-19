from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import yaml

from packages.domains.cti import CtiDomainAdapter, CtiChunk
from packages.evidence.ids import canonical_json
from packages.evidence.policy import PolicyDenied, Principal, PublicFixturePolicy
from packages.evidence.schema import ExternalIdentifier, SnapshotRef
from packages.evidence.store import EvidenceStore
from packages.indexing.chunker import ChunkingConfig, DeterministicTokenizer, chunk_objects
from packages.indexing.cli import _generation_manifest, ingest_fixture
from packages.indexing.graph_indexer import CatalogGraphProjectionWriter, reconstruct_catalog_graph
from packages.indexing.lexical_indexer import ExactProjectionWriter, LexicalProjectionWriter
from packages.indexing.manifests import GenerationManifest, ProjectionReceipt
from packages.indexing.orchestrator import PublicationOrchestrator
from packages.retrieval.dense import DenseIndex, DenseProjectionWriter
from packages.retrieval.exact import ExactIndex
from packages.retrieval.lexical import LexicalIndex
from packages.retrieval.providers import DeterministicFixtureEmbeddingProvider

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CONFIG = ROOT / "benchmark" / "advanced" / "configs" / "fixture.yaml"
CORPUS_MANIFEST = ROOT / "tests" / "fixtures" / "cti" / "corpus.manifest.json"


def _batch_and_raw(*, name_suffix: str = ""):
    fixture = ROOT / "tests" / "fixtures" / "cti" / "public_fixture.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    if name_suffix:
        payload["objects"][0]["name"] += name_suffix
        payload["source_snapshot_id"] += name_suffix.replace(" ", "-")
    batch = CtiDomainAdapter().normalize(payload)
    candidates: dict[str, bytes] = {}
    for record in payload["objects"] + payload["relations"]:
        encoded = canonical_json(record).encode("utf-8")
        candidates[sha256(encoded).hexdigest()] = encoded
    source_id_by_uid = {
        obj.uid: obj.source_refs[0].source_object_id for obj in batch.objects if obj.source_refs
    }
    for relation in batch.relations:
        if relation.assertion_kind != "embedded_reference":
            continue
        source_id = source_id_by_uid[relation.source_object_uid]
        target_id = source_id_by_uid[relation.target_object_uid]
        record = {
            "source_record_id": source_id,
            "source_object_id": source_id,
            "target_object_id": target_id,
            "original_relation": "object_refs",
            "normalized_relation": "references",
            "assertion_kind": "embedded_reference",
            "source_field_path": relation.source_field_path,
        }
        encoded = canonical_json(record).encode("utf-8")
        candidates[sha256(encoded).hexdigest()] = encoded
    required = {
        ref.raw_payload_sha256
        for value in (*batch.objects, *batch.relations)
        for ref in (value.source_refs if hasattr(value, "source_refs") else value.evidence_refs)
    }
    return batch, {digest: candidates[digest] for digest in sorted(required)}


def _temp_config(tmp_path: Path) -> Path:
    payload = yaml.safe_load(FIXTURE_CONFIG.read_text(encoding="utf-8"))
    payload["state_dir"] = str(tmp_path / "state")
    path = tmp_path / "fixture.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _policy_scope():
    policy = PublicFixturePolicy.trusted(
        corpus_id="fixture-cti",
        scope_id="public-fixture",
        source_allowlist=frozenset({"fixture-public"}),
    )
    scope = policy.resolve_scope(
        Principal(principal_id="e2e", source="trusted_local_cli"), "fixture-cti"
    )
    return policy, scope


def test_fixture_ingest_publishes_all_local_projections_and_no_change_reingest_is_stable(tmp_path):
    config = _temp_config(tmp_path)
    first = ingest_fixture(config_path=config, manifest_path=CORPUS_MANIFEST)
    second = ingest_fixture(config_path=config, manifest_path=CORPUS_MANIFEST)
    assert first["generation_id"] == second["generation_id"]
    assert second["logical_changes"] == 0
    assert first["required_projections"] == ["dense", "exact", "graph", "lexical"]
    assert first["dense"] == "configured"
    assert first["graph"] == "configured"
    assert first["network_used"] is False

    state = tmp_path / "state"
    with EvidenceStore(state / "catalog.db", state / "raw") as store:
        row = store.connection.execute(
            "SELECT generation_id,manifest_sha256 FROM active_generations "
            "WHERE domain='cti' AND scope_id='public-fixture' AND corpus_id='fixture-cti'"
        ).fetchone()
        assert row is not None and row["generation_id"] == first["generation_id"]
        snapshot = SnapshotRef(
            domain="cti",
            scope_id="public-fixture",
            snapshot_id=row["generation_id"],
            manifest_sha256=row["manifest_sha256"],
        )
        policy, scope = _policy_scope()
        exact = ExactIndex.open(
            store,
            path=ExactIndex.path_for(
                state / "indexes",
                domain="cti",
                scope_id="public-fixture",
                generation_id=row["generation_id"],
            ),
        )
        assert exact.lookup(
            ExternalIdentifier(namespace="cve", value="CVE-2026-999999", domain="cti"),
            scope=scope,
            snapshot=snapshot,
        )
        lexical = LexicalIndex.open(
            store,
            path=LexicalIndex.path_for(
                state / "indexes",
                domain="cti",
                scope_id="public-fixture",
                generation_id=row["generation_id"],
            ),
        )
        assert lexical.search("causality", scope=scope, snapshot=snapshot)
        restricted_hits = lexical.search("restricted", scope=scope, snapshot=snapshot)
        denied = 0
        for hit in restricted_hits:
            try:
                lexical.hydrate(hit, scope=scope, snapshot=snapshot, policy=policy)
            except PolicyDenied:
                denied += 1
        assert denied >= 1

        provider = DeterministicFixtureEmbeddingProvider()
        dense = DenseIndex.open(
            store,
            path=DenseIndex.path_for(
                state / "indexes",
                domain="cti",
                scope_id="public-fixture",
                generation_id=row["generation_id"],
            ),
            provider=provider,
        )
        assert dense.policy_excluded_chunk_uids
        excluded = set(dense.policy_excluded_chunk_uids)
        assert excluded.isdisjoint({entry["chunk_uid"] for entry in dense.entries})

        manifest_row = store.connection.execute(
            "SELECT manifest_json FROM generation_manifests "
            "WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?",
            ("cti", "public-fixture", "fixture-cti", row["generation_id"]),
        ).fetchone()
        receipt_row = store.connection.execute(
            "SELECT receipt_json FROM projection_receipts "
            "WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=? AND backend='graph'",
            ("cti", "public-fixture", "fixture-cti", row["generation_id"]),
        ).fetchone()
        assert manifest_row is not None and receipt_row is not None
        manifest = GenerationManifest.model_validate_json(manifest_row["manifest_json"])
        receipt = ProjectionReceipt.model_validate_json(receipt_row["receipt_json"])
        graph_writer = CatalogGraphProjectionWriter(store)
        assert graph_writer.verify(manifest, receipt)
        reconstructed = reconstruct_catalog_graph(store, manifest)
        assert reconstructed.objects and reconstructed.assertions


def _chunk_batch(batch):
    tokenizer = DeterministicTokenizer()
    chunks = chunk_objects(
        batch.objects,
        serialization_hints=CtiDomainAdapter().field_serialization_hints(),
        tokenizer=tokenizer,
        config=ChunkingConfig(),
        chunk_class=CtiChunk,
    )
    return batch.model_copy(update={"chunks": chunks}), tokenizer


def _writers(store, root, tokenizer):
    policy, scope = _policy_scope()
    exact = ExactProjectionWriter(store, root)
    lexical = LexicalProjectionWriter(store, root, tokenizer=tokenizer)
    provider = DeterministicFixtureEmbeddingProvider()
    dense = DenseProjectionWriter(
        store,
        root,
        provider=provider,
        scope=scope,
        policy=policy,
        destination="local_generator",
    )
    graph = CatalogGraphProjectionWriter(store)
    return exact, lexical, dense, graph


def test_changed_object_publishes_new_chunk_membership_without_reusing_old_chunk(tmp_path):
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        old_batch, old_raw = _batch_and_raw()
        old_batch, tokenizer = _chunk_batch(old_batch)
        store.persist_batch(old_batch, raw_payloads=old_raw)
        exact, lexical, dense, graph = _writers(store, tmp_path / "indexes", tokenizer)
        old_manifest = _generation_manifest(
            old_batch,
            corpus_id="fixture-cti",
            exact_writer=exact,
            lexical_writer=lexical,
            dense_writer=dense,
            graph_writer=graph,
            tokenizer=tokenizer,
            chunk_config=ChunkingConfig(),
        )
        PublicationOrchestrator.trusted(store, [exact, lexical, dense, graph]).publish(old_manifest)
        old_object = old_batch.objects[0]
        old_chunks = {chunk.uid for chunk in old_batch.chunks if chunk.object_uid == old_object.uid}
        assert old_chunks

        new_batch, new_raw = _batch_and_raw(name_suffix=" v2")
        new_batch, tokenizer2 = _chunk_batch(new_batch)
        store.persist_batch(new_batch, raw_payloads=new_raw)
        exact2, lexical2, dense2, graph2 = _writers(store, tmp_path / "indexes", tokenizer2)
        new_manifest = _generation_manifest(
            new_batch,
            corpus_id="fixture-cti",
            exact_writer=exact2,
            lexical_writer=lexical2,
            dense_writer=dense2,
            graph_writer=graph2,
            tokenizer=tokenizer2,
            chunk_config=ChunkingConfig(),
        )
        PublicationOrchestrator.trusted(store, [exact2, lexical2, dense2, graph2]).publish(new_manifest)
        new_chunks = {chunk.uid for chunk in new_batch.chunks if chunk.object_uid == old_object.uid}
        assert new_chunks and old_chunks.isdisjoint(new_chunks)
        active_chunk_membership = {
            member["evidence_uid"]
            for member in store.connection.execute(
                "SELECT evidence_uid FROM snapshot_membership "
                "WHERE domain=? AND scope_id=? AND snapshot_id=? AND evidence_kind='chunk'",
                (new_manifest.domain, new_manifest.scope_id, new_manifest.generation_id),
            )
        }
        assert new_chunks <= active_chunk_membership
        assert old_chunks.isdisjoint(active_chunk_membership)
