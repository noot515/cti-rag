from __future__ import annotations

from pathlib import Path

import pytest

from packages.evidence.lifecycle import LifecycleAuthority
from packages.evidence.policy import Principal, PublicFixturePolicy
from packages.evidence.snapshot import EvidenceWithdrawn, ReceiptMismatch, SnapshotCatalog, SnapshotManager
from packages.evidence.store import EvidenceStore
from packages.indexing.orchestrator import PublicationOrchestrator

from ._helpers import FakeProjectionWriter, batch_and_raw, generation_manifest, snapshot_for


def _scope():
    policy = PublicFixturePolicy.trusted(source_allowlist=frozenset({"fixture-public"}))
    return policy.resolve_scope(Principal(principal_id="index-test", source="trusted_local_cli"), "fixture-cti")


def _persist(store, batch, raw, manifest):
    store.persist_batch(batch, raw_payloads=raw, snapshot=snapshot_for(manifest))


def _publish(store, manifest, *, exact=None, lexical=None):
    exact = exact or FakeProjectionWriter("exact", store=store)
    lexical = lexical or FakeProjectionWriter("lexical", store=store)
    orchestrator = PublicationOrchestrator.trusted(store, [exact, lexical])
    orchestrator.publish(manifest)
    return orchestrator


def test_atomic_pointer_and_reader_pin_never_switch_mid_request(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw") as store:
        first_batch, first_raw = batch_and_raw()
        first_manifest = generation_manifest(first_batch)
        _persist(store, first_batch, first_raw, first_manifest)
        _publish(store, first_manifest)

        manager = SnapshotManager(store)
        old_handle = manager.pin_active(_scope())
        old_revision = first_batch.objects[0].revision_uid
        assert old_handle.get_revision(old_revision)["revision_uid"] == old_revision
        assert manager.pin_count(first_manifest.generation_id) == 1

        second_batch, second_raw = batch_and_raw(name_suffix=" v2")
        second_manifest = generation_manifest(second_batch)
        _persist(store, second_batch, second_raw, second_manifest)
        _publish(store, second_manifest)

        active = SnapshotCatalog(store).active_generation("cti", "public-fixture", "fixture-cti")
        assert active["generation_id"] == second_manifest.generation_id
        assert old_handle.snapshot.snapshot_id == first_manifest.generation_id
        assert old_handle.get_revision(old_revision)["revision_uid"] == old_revision

        with manager.pin_active(_scope()) as new_handle:
            assert new_handle.snapshot.snapshot_id == second_manifest.generation_id
            assert new_handle.get_revision(second_batch.objects[0].revision_uid) is not None
        old_handle.release()
        assert manager.pin_count(first_manifest.generation_id) == 0

        count = store.connection.execute(
            "SELECT COUNT(*) FROM generation_manifests WHERE domain='cti' AND scope_id='public-fixture'"
        ).fetchone()[0]
        assert count == 2


def test_partial_required_projection_never_becomes_active_and_old_pointer_survives(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw") as store:
        batch1, raw1 = batch_and_raw()
        manifest1 = generation_manifest(batch1)
        _persist(store, batch1, raw1, manifest1)
        _publish(store, manifest1)

        batch2, raw2 = batch_and_raw(name_suffix=" failed candidate")
        manifest2 = generation_manifest(batch2)
        _persist(store, batch2, raw2, manifest2)
        exact = FakeProjectionWriter("exact", store=store)
        lexical = FakeProjectionWriter("lexical", store=store, fail_build=True)
        with pytest.raises(RuntimeError, match="lexical build failed"):
            _publish(store, manifest2, exact=exact, lexical=lexical)

        catalog = SnapshotCatalog(store)
        assert catalog.state(manifest2) == "failed"
        assert catalog.active_generation("cti", "public-fixture", "fixture-cti")["generation_id"] == manifest1.generation_id
        assert store.get_snapshot("cti", "public-fixture", manifest2.generation_id)["active"] is False


def test_disabled_optional_channels_are_explicit_and_do_not_block_ready(tmp_path: Path):
    batch, raw = batch_and_raw()
    manifest = generation_manifest(batch, dense=False, graph=False)
    assert [(p.backend, p.enabled, p.required) for p in manifest.projections] == [
        ("dense", False, False),
        ("exact", True, True),
        ("graph", False, False),
        ("lexical", True, True),
    ]
    with EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw") as store:
        _persist(store, batch, raw, manifest)
        _publish(store, manifest)
        rows = store.connection.execute(
            "SELECT backend FROM projection_jobs WHERE generation_id=? ORDER BY backend", (manifest.generation_id,)
        ).fetchall()
        assert [row["backend"] for row in rows] == ["exact", "lexical"]
        assert SnapshotCatalog(store).state(manifest) == "active"


@pytest.mark.parametrize("mutation", ["scope", "manifest", "fingerprint"])
def test_wrong_scope_hash_or_fingerprint_receipt_cannot_satisfy_readiness(tmp_path: Path, mutation: str):
    batch, raw = batch_and_raw()
    manifest = generation_manifest(batch, lexical=False)
    with EvidenceStore(tmp_path / f"{mutation}.sqlite3", tmp_path / f"raw-{mutation}") as store:
        _persist(store, batch, raw, manifest)
        catalog = SnapshotCatalog(store)
        catalog.register_generation(manifest)
        bad = FakeProjectionWriter("exact", store=store, mutate=mutation).build(manifest)
        with pytest.raises(ReceiptMismatch):
            catalog.record_receipt(manifest, bad)
        assert catalog.all_verified(manifest) is False
        assert store.get_snapshot("cti", "public-fixture", manifest.generation_id)["active"] is False


def test_revocation_is_live_overlay_even_for_older_pinned_handle(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw") as store:
        old_batch, old_raw = batch_and_raw()
        old_manifest = generation_manifest(old_batch)
        _persist(store, old_batch, old_raw, old_manifest)
        _publish(store, old_manifest)
        manager = SnapshotManager(store)
        handle = manager.pin_active(_scope())
        old_revision = old_batch.objects[0].revision_uid
        assert handle.get_revision(old_revision) is not None

        revoked_batch, revoked_raw = batch_and_raw(name_suffix=" revoked", revoked=True)
        assert revoked_batch.objects[0].uid == old_batch.objects[0].uid
        revoked_manifest = generation_manifest(revoked_batch)
        _persist(store, revoked_batch, revoked_raw, revoked_manifest)

        revoked_object = revoked_batch.objects[0]
        source_ref = revoked_object.source_refs[0]
        LifecycleAuthority(store).record_inventory(
            domain=revoked_object.domain,
            scope_id=revoked_object.scope_id,
            source_instance=source_ref.source_instance,
            supported_type=revoked_object.object_type,
            type_fingerprint="publication-test-type-v1",
            filter_fingerprint="publication-test-filter-v1",
            seen_source_ids=(source_ref.source_object_id,),
            current_revisions={
                source_ref.source_object_id: {
                    ("object", revoked_object.uid, revoked_object.revision_uid)
                }
            },
            explicit_status={source_ref.source_object_id: "revoked"},
            complete=True,
            authorized=True,
            page_count=1,
            capture_started_at="2026-09-19T00:00:00Z",
            capture_completed_at="2026-09-19T00:00:01Z",
            max_staleness_seconds=3600,
        )
        with pytest.raises(EvidenceWithdrawn):
            handle.get_revision(old_revision)
        handle.release()


def test_active_pointer_is_unique_per_domain_scope_and_corpus(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw") as store:
        batch, raw = batch_and_raw()
        one = generation_manifest(batch, corpus_id="fixture-cti-a")
        two = generation_manifest(batch, corpus_id="fixture-cti-b")
        _persist(store, batch, raw, one)
        _publish(store, one)
        _persist(store, batch, raw, two)
        _publish(store, two)
        catalog = SnapshotCatalog(store)
        assert catalog.active_generation("cti", "public-fixture", "fixture-cti-a")["generation_id"] == one.generation_id
        assert catalog.active_generation("cti", "public-fixture", "fixture-cti-b")["generation_id"] == two.generation_id
        assert store.get_snapshot("cti", "public-fixture", one.generation_id)["active"] is True
        assert store.get_snapshot("cti", "public-fixture", two.generation_id)["active"] is True
