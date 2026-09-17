from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from packages.evidence.snapshot import SnapshotCatalog
from packages.evidence.store import EvidenceStore
from packages.indexing.orchestrator import InjectedPublicationCrash, PublicationOrchestrator

from ._helpers import FakeProjectionWriter, batch_and_raw, generation_manifest, snapshot_for


def _prepare(store, *, suffix=""):
    batch, raw = batch_and_raw(name_suffix=suffix)
    manifest = generation_manifest(batch)
    store.persist_batch(batch, raw_payloads=raw, snapshot=snapshot_for(manifest))
    writers = [FakeProjectionWriter("exact", store=store), FakeProjectionWriter("lexical", store=store)]
    return batch, manifest, PublicationOrchestrator.trusted(store, writers)


def test_jobs_exist_before_backend_writes_and_visibility_is_required(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw") as store:
        _, manifest, _ = _prepare(store)
        exact = FakeProjectionWriter("exact", store=store)
        lexical = FakeProjectionWriter("lexical", store=store, visibility=False)
        orchestrator = PublicationOrchestrator.trusted(store, [exact, lexical])
        with pytest.raises(Exception):
            orchestrator.publish(manifest)
        assert exact.build_calls == 1
        assert lexical.build_calls == 1
        assert SnapshotCatalog(store).active_generation("cti", "public-fixture", "fixture-cti") is None


def test_restart_after_all_receipts_recovers_ready_and_activation(tmp_path: Path):
    db = tmp_path / "catalog.sqlite3"
    raw_root = tmp_path / "raw"
    with EvidenceStore(db, raw_root) as store:
        _, manifest, orchestrator = _prepare(store)
        with pytest.raises(InjectedPublicationCrash, match="after_receipt:lexical"):
            orchestrator.publish(manifest, crash_at="after_receipt:lexical")
        assert SnapshotCatalog(store).state(manifest) == "building"
        assert SnapshotCatalog(store).active_generation("cti", "public-fixture", "fixture-cti") is None

    with EvidenceStore(db, raw_root) as restarted:
        recovered = PublicationOrchestrator.trusted(restarted, []).recover("cti", "public-fixture", "fixture-cti")
        assert recovered["generation_id"] == manifest.generation_id
        row = restarted.connection.execute(
            "SELECT status FROM publication_jobs WHERE generation_id=?", (manifest.generation_id,)
        ).fetchone()
        assert row["status"] == "completed"


def test_crash_after_ready_preserves_old_pointer_until_recovery(tmp_path: Path):
    db = tmp_path / "catalog.sqlite3"
    raw_root = tmp_path / "raw"
    with EvidenceStore(db, raw_root) as store:
        _, old_manifest, old_orchestrator = _prepare(store)
        old_orchestrator.publish(old_manifest)
        _, new_manifest, new_orchestrator = _prepare(store, suffix=" v2")
        with pytest.raises(InjectedPublicationCrash, match="after_ready"):
            new_orchestrator.publish(new_manifest, crash_at="after_ready")
        catalog = SnapshotCatalog(store)
        assert catalog.state(new_manifest) == "ready"
        assert catalog.active_generation("cti", "public-fixture", "fixture-cti")["generation_id"] == old_manifest.generation_id

    with EvidenceStore(db, raw_root) as restarted:
        recovered = PublicationOrchestrator.trusted(restarted, []).recover("cti", "public-fixture", "fixture-cti")
        assert recovered["generation_id"] == new_manifest.generation_id


def test_crash_after_activation_reconciles_durable_pointer_and_job_ack(tmp_path: Path):
    db = tmp_path / "catalog.sqlite3"
    raw_root = tmp_path / "raw"
    with EvidenceStore(db, raw_root) as store:
        _, manifest, orchestrator = _prepare(store)
        with pytest.raises(InjectedPublicationCrash, match="after_activation"):
            orchestrator.publish(manifest, crash_at="after_activation")
        catalog = SnapshotCatalog(store)
        assert catalog.active_generation("cti", "public-fixture", "fixture-cti")["generation_id"] == manifest.generation_id
        assert store.connection.execute(
            "SELECT status FROM publication_jobs WHERE generation_id=?", (manifest.generation_id,)
        ).fetchone()["status"] == "activated"

    with EvidenceStore(db, raw_root) as restarted:
        recovered = PublicationOrchestrator.trusted(restarted, []).recover("cti", "public-fixture", "fixture-cti")
        assert recovered["generation_id"] == manifest.generation_id
        assert restarted.connection.execute(
            "SELECT status FROM publication_jobs WHERE generation_id=?", (manifest.generation_id,)
        ).fetchone()["status"] == "completed"


def test_crash_after_first_receipt_does_not_activate_incomplete_generation(tmp_path: Path):
    db = tmp_path / "catalog.sqlite3"
    raw_root = tmp_path / "raw"
    with EvidenceStore(db, raw_root) as store:
        _, manifest, orchestrator = _prepare(store)
        with pytest.raises(InjectedPublicationCrash, match="after_receipt:exact"):
            orchestrator.publish(manifest, crash_at="after_receipt:exact")
        assert SnapshotCatalog(store).active_generation("cti", "public-fixture", "fixture-cti") is None
    with EvidenceStore(db, raw_root) as restarted:
        recovered = PublicationOrchestrator.trusted(restarted, []).recover("cti", "public-fixture", "fixture-cti")
        assert recovered is None
        assert SnapshotCatalog(restarted).state(manifest) == "building"


def test_advanced_publication_import_is_fresh_process_safe(tmp_path: Path):
    root = Path(__file__).resolve().parents[3]
    code = (
        "import sys; import packages.indexing.orchestrator, packages.evidence.snapshot; "
        "print(int('packages.manager.kb_db_manager' in sys.modules), int('sqlalchemy' in sys.modules), int('pymilvus' in sys.modules))"
    )
    env = {**os.environ, "PYTHONPATH": str(root)}
    result = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, text=True, capture_output=True, check=True)
    assert result.stdout.strip() == "0 0 0"
