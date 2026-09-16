from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from packages.domains.cti import CtiDomainAdapter
from packages.evidence.ids import canonical_json, chunk_uid
from packages.evidence.policy import DenyByDefaultPolicy, PolicyDenied, Principal, PublicFixturePolicy
from packages.evidence.schema import AuthorizedEvidenceView, EvidenceChunk, SnapshotRef
from packages.evidence.store import (
    CheckpointUpdate,
    ConcurrentWriterError,
    EvidenceStore,
    ForeignKeyMismatch,
    ImmutableRevisionConflict,
    InjectedPersistenceFailure,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "cti" / "public_fixture.json"


def _manifest():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _batch_and_raw(scope_id: str = "public-fixture"):
    manifest = _manifest()
    manifest["scope_id"] = scope_id
    batch = CtiDomainAdapter().normalize(manifest)
    raw: dict[str, bytes] = {}
    for record in manifest["objects"] + manifest["relations"]:
        payload = canonical_json(record).encode("utf-8")
        raw[sha256(payload).hexdigest()] = payload

    obj = batch.objects[0]
    text = "synthetic chunk"
    content_hash = sha256(text.encode()).hexdigest()
    chunk_id = chunk_uid(
        object_id=obj.uid,
        object_revision_id=obj.revision_uid,
        chunker_fingerprint="fixture-chunker-v1",
        section_path="description",
        ordinal=0,
        content_hash=content_hash,
    )
    chunk = EvidenceChunk(
        uid=chunk_id,
        object_uid=obj.uid,
        object_revision_uid=obj.revision_uid,
        domain="cti",
        scope_id=scope_id,
        chunker_fingerprint="fixture-chunker-v1",
        section_path="description",
        ordinal=0,
        text=text,
        content_hash=content_hash,
        token_count=2,
        tokenizer_fingerprint="fixture-tokenizer-v1",
        source_refs=obj.source_refs,
        policy=obj.policy,
    )
    batch = batch.model_copy(update={"chunks": (chunk,)})
    return batch, raw


def _snapshot(scope_id: str = "public-fixture") -> SnapshotRef:
    return SnapshotRef(
        domain="cti",
        scope_id=scope_id,
        snapshot_id="snapshot-v1",
        manifest_sha256="a" * 64,
    )


def test_restart_persistence_replay_zero_changes_and_snapshot_inactive(tmp_path: Path):
    batch, raw = _batch_and_raw()
    db = tmp_path / "state" / "catalog.sqlite3"
    raw_root = tmp_path / "raw"
    with EvidenceStore(db, raw_root) as store:
        first = store.persist_batch(
            batch,
            raw_payloads=raw,
            snapshot=_snapshot(),
            checkpoint=CheckpointUpdate(source_instance="fixture-public", cursor={"offset": 7}),
        )
        assert first.logical_changes > 0
        assert store.get_snapshot("cti", "public-fixture", "snapshot-v1")["active"] is False
        assert store.resolve_external_ids("cti", "public-fixture", "cve", "CVE-2026-999999")
        assert store.get_chunk("cti", "public-fixture", batch.chunks[0].uid) is not None

    with EvidenceStore(db, raw_root) as reopened:
        assert reopened.get_revision(
            "cti", "public-fixture", batch.objects[0].revision_uid
        ) is not None
        assert reopened.get_checkpoint("cti", "public-fixture", "fixture-public") == {"offset": 7}
        replay = reopened.persist_batch(
            batch,
            raw_payloads=raw,
            snapshot=_snapshot(),
            checkpoint=CheckpointUpdate(source_instance="fixture-public", cursor={"offset": 7}),
        )
        assert replay.logical_changes == 0


def test_conflicting_immutable_revision_is_rejected(tmp_path: Path):
    batch, raw = _batch_and_raw()
    with EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw") as store:
        store.persist_batch(batch, raw_payloads=raw)
        changed = batch.objects[0].model_copy(update={"name": "tampered semantic content"})
        bad = batch.model_copy(update={"objects": (changed, *batch.objects[1:])})
        with pytest.raises(ImmutableRevisionConflict):
            store.persist_batch(bad, raw_payloads=raw)


def test_same_logical_object_can_exist_in_two_scopes_without_cross_scope_join(tmp_path: Path):
    batch_a, raw = _batch_and_raw("scope-a")
    batch_b, _ = _batch_and_raw("scope-b")
    assert batch_a.objects[0].uid == batch_b.objects[0].uid
    with EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw") as store:
        store.persist_batch(batch_a, raw_payloads=raw)
        store.persist_batch(batch_b, raw_payloads=raw)
        assert len(store.resolve_external_ids("cti", "scope-a", "cve", "CVE-2026-999999")) == 1
        assert len(store.resolve_external_ids("cti", "scope-b", "cve", "CVE-2026-999999")) == 1
        assert len(store.list_scoped_revisions("cti", "scope-a")) == len(
            store.list_scoped_revisions("cti", "scope-b")
        )


def test_dangling_assertion_rolls_back_and_does_not_advance_checkpoint(tmp_path: Path):
    batch, raw = _batch_and_raw()
    relation = batch.relations[0].model_copy(update={"target_object_uid": "f" * 64})
    bad = batch.model_copy(update={"relations": (relation, *batch.relations[1:])})
    with EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw") as store:
        with pytest.raises(ForeignKeyMismatch):
            store.persist_batch(
                bad,
                raw_payloads=raw,
                checkpoint=CheckpointUpdate(source_instance="fixture-public", cursor={"offset": 99}),
            )
        assert store.get_checkpoint("cti", "public-fixture", "fixture-public") is None
        assert store.list_scoped_revisions("cti", "public-fixture") == ()


def test_crash_after_raw_rename_leaves_orphan_but_no_catalog_reference_or_checkpoint(tmp_path: Path):
    batch, raw = _batch_and_raw()
    with EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw") as store:
        with pytest.raises(InjectedPersistenceFailure):
            store.persist_batch(
                batch,
                raw_payloads=raw,
                checkpoint=CheckpointUpdate(source_instance="fixture-public", cursor={"offset": 1}),
                fail_after_raw=True,
            )
        assert any(
            path.is_file()
            for path in (tmp_path / "raw").rglob("*")
            if len(path.name) == 64
        )
        assert store.connection.execute("SELECT COUNT(*) FROM raw_payloads").fetchone()[0] == 0
        assert store.get_checkpoint("cti", "public-fixture", "fixture-public") is None


def test_concurrent_writer_is_rejected(tmp_path: Path):
    batch, raw = _batch_and_raw()
    first = EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw")
    second = EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw")
    try:
        with first.writer_lock():
            with pytest.raises(ConcurrentWriterError):
                second.persist_batch(batch, raw_payloads=raw)
    finally:
        second.close()
        first.close()


def test_raw_hydration_and_hash_lookup_require_policy_and_evidence_link(tmp_path: Path):
    batch, raw = _batch_and_raw()
    obj = batch.objects[0]
    digest = obj.source_refs[0].raw_payload_sha256
    with EvidenceStore(tmp_path / "catalog.sqlite3", tmp_path / "raw") as store:
        store.persist_batch(batch, raw_payloads=raw)
        policy = PublicFixturePolicy.trusted(source_allowlist=frozenset({"fixture-public"}))
        scope = policy.resolve_scope(
            Principal(principal_id="tester", source="trusted_local_cli"), "fixture-cti"
        )
        view = AuthorizedEvidenceView(
            evidence_uid=obj.uid,
            domain="cti",
            scope_id="public-fixture",
            source_instances=("fixture-public",),
            policy=obj.policy,
        )
        assert store.raw_metadata(digest, scope=scope, policy=policy, view=view)["sha256"] == digest
        assert store.hydrate_raw(digest, scope=scope, policy=policy, view=view) == raw[digest]

        denied = AuthorizedEvidenceView(
            evidence_uid=obj.uid,
            domain="cti",
            scope_id="public-fixture",
            source_instances=("not-allowed",),
            policy=obj.policy,
        )
        with pytest.raises(PolicyDenied):
            store.raw_metadata("0" * 64, scope=scope, policy=policy, view=denied)
        with pytest.raises(PermissionError):
            store.raw_metadata("0" * 64, scope=scope, policy=policy, view=view)
        with pytest.raises(PolicyDenied):
            store.hydrate_raw(digest, scope=scope, policy=DenyByDefaultPolicy(), view=view)


def test_store_import_does_not_connect_to_legacy_database(tmp_path: Path):
    root = Path(__file__).resolve().parents[3]
    code = (
        "import sys; import packages.evidence.store; "
        "print(int('packages.manager.kb_db_manager' in sys.modules), "
        "int('sqlalchemy' in sys.modules), int('pymysql' in sys.modules))"
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
    assert result.stdout.strip() == "0 0 0"
