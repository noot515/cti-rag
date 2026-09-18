"""Durable scoped evidence catalog; no legacy DB imports or import-time connections."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from .domain import NormalizedEvidenceBatch
from .ids import canonical_json
from .migrations import apply_migrations
from .policy import ResolvedScope, RetrievalPolicy, require_authorized
from .raw_store import RawPayloadStore, RawStoreError
from .schema import (
    AuthorizedEvidenceView,
    EvidenceChunk,
    EvidenceObject,
    EvidenceRelation,
    SnapshotRef,
    SourceRef,
)


class StoreError(RuntimeError):
    pass


class ImmutableRevisionConflict(StoreError):
    pass


class ForeignKeyMismatch(StoreError):
    pass


class ConcurrentWriterError(StoreError):
    pass


class InjectedPersistenceFailure(StoreError):
    pass


@dataclass(frozen=True)
class CheckpointUpdate:
    source_instance: str
    cursor: Mapping[str, Any]


@dataclass(frozen=True)
class PersistResult:
    logical_changes: int
    raw_payloads_written: int
    objects_seen: int
    relations_seen: int
    chunks_seen: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


class ProcessWriterLock:
    """One cross-process writer using a lock file; readers remain SQLite-managed."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._handle = None

    def acquire(self) -> None:
        _private_dir(self.path.parent)
        handle = open(self.path, "a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as exc:
            handle.close()
            raise ConcurrentWriterError(
                f"another evidence-catalog writer holds {self.path.name}"
            ) from exc
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


def _semantic_payload(value: EvidenceObject | EvidenceRelation | EvidenceChunk) -> str:
    if isinstance(value, EvidenceObject):
        payload = value.model_dump(mode="json", exclude={"source_refs", "raw_payload_ref"})
    elif isinstance(value, EvidenceRelation):
        payload = value.model_dump(mode="json", exclude={"evidence_refs"})
    else:
        payload = value.model_dump(mode="json", exclude={"source_refs"})
    return canonical_json(payload)


def _sources(value: EvidenceObject | EvidenceRelation | EvidenceChunk) -> tuple[SourceRef, ...]:
    if isinstance(value, EvidenceObject):
        return value.source_refs
    if isinstance(value, EvidenceRelation):
        return value.evidence_refs
    return value.source_refs


class EvidenceStore:
    """Explicitly constructed SQLite catalog and private raw payload store."""

    def __init__(self, catalog_path: Path | str, raw_root: Path | str) -> None:
        self.catalog_path = Path(catalog_path)
        _private_dir(self.catalog_path.parent)
        self.raw_store = RawPayloadStore(raw_root)
        self.lock_path = self.catalog_path.with_name(self.catalog_path.name + ".writer.lock")
        self._writer_lock = ProcessWriterLock(self.lock_path)
        self.connection = sqlite3.connect(
            self.catalog_path,
            timeout=0.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA busy_timeout=0")
        try:
            with self._writer_lock:
                apply_migrations(self.connection)
        except Exception:
            self.connection.close()
            raise
        try:
            os.chmod(self.catalog_path, 0o600)
        except OSError:
            pass

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @contextmanager
    def writer_lock(self):
        with self._writer_lock:
            yield

    def _raw_for_sources(
        self, sources: tuple[SourceRef, ...], provided: Mapping[str, bytes]
    ) -> dict[str, bytes]:
        resolved: dict[str, bytes] = {}
        for ref in sources:
            digest = ref.raw_payload_sha256
            if digest in resolved:
                continue
            if digest in provided:
                raw = bytes(provided[digest])
                self.raw_store.put(raw, expected_sha256=digest)
                resolved[digest] = raw
            else:
                try:
                    resolved[digest] = self.raw_store.read(digest)
                except RawStoreError as exc:
                    raise StoreError(
                        f"raw payload bytes are required before catalog persistence: {digest}"
                    ) from exc
        return resolved

    def _insert_or_verify(
        self,
        table: str,
        key_where: str,
        key_values: tuple[Any, ...],
        insert_sql: str,
        insert_values: tuple[Any, ...],
        payload_column: str,
        payload: str,
    ) -> int:
        row = self.connection.execute(
            f"SELECT {payload_column} FROM {table} WHERE {key_where}", key_values
        ).fetchone()
        if row is not None:
            if row[payload_column] != payload:
                raise ImmutableRevisionConflict(f"conflicting immutable revision in {table}")
            return 0
        self.connection.execute(insert_sql, insert_values)
        return 1

    def persist_batch(
        self,
        batch: NormalizedEvidenceBatch,
        *,
        raw_payloads: Mapping[str, bytes],
        snapshot: SnapshotRef | None = None,
        checkpoint: CheckpointUpdate | None = None,
        fail_after_raw: bool = False,
    ) -> PersistResult:
        if snapshot is not None and (
            snapshot.domain != batch.domain or snapshot.scope_id != batch.scope_id
        ):
            raise ForeignKeyMismatch("snapshot domain/scope does not match batch")

        all_values = tuple(batch.objects) + tuple(batch.relations) + tuple(batch.chunks)
        all_sources = tuple(ref for value in all_values for ref in _sources(value))
        if any(ref.domain != batch.domain for ref in all_sources):
            raise ForeignKeyMismatch("source reference domain does not match batch")

        with self._writer_lock:
            resolved_raw = self._raw_for_sources(all_sources, raw_payloads)
            if fail_after_raw:
                raise InjectedPersistenceFailure(
                    "injected failure after atomic raw publication and before catalog transaction"
                )

            changes = 0
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                now = _now()

                for ref in all_sources:
                    raw = resolved_raw[ref.raw_payload_sha256]
                    cur = self.connection.execute(
                        "INSERT OR IGNORE INTO raw_payloads(domain,scope_id,sha256,byte_length,created_at) VALUES (?,?,?,?,?)",
                        (batch.domain, batch.scope_id, ref.raw_payload_sha256, len(raw), now),
                    )
                    changes += max(cur.rowcount, 0)
                    cur = self.connection.execute(
                        "INSERT OR IGNORE INTO raw_payload_sources(domain,scope_id,sha256,source_instance,source_object_id,normalizer_version,source_snapshot_id,upstream_origin,source_uri) VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            batch.domain,
                            batch.scope_id,
                            ref.raw_payload_sha256,
                            ref.source_instance,
                            ref.source_object_id,
                            ref.normalizer_version,
                            ref.source_snapshot_id,
                            ref.upstream_origin,
                            ref.source_uri,
                        ),
                    )
                    changes += max(cur.rowcount, 0)

                for obj in batch.objects:
                    if obj.domain != batch.domain or obj.scope_id != batch.scope_id:
                        raise ForeignKeyMismatch("object domain/scope does not match batch")
                    cur = self.connection.execute(
                        "INSERT OR IGNORE INTO objects(domain,scope_id,object_uid) VALUES (?,?,?)",
                        (batch.domain, batch.scope_id, obj.uid),
                    )
                    changes += max(cur.rowcount, 0)
                    payload = _semantic_payload(obj)
                    changes += self._insert_or_verify(
                        "object_revisions",
                        "domain=? AND scope_id=? AND revision_uid=?",
                        (batch.domain, batch.scope_id, obj.revision_uid),
                        "INSERT INTO object_revisions(domain,scope_id,object_uid,revision_uid,payload_json,lifecycle_state,created_at) VALUES (?,?,?,?,?,?,?)",
                        (
                            batch.domain,
                            batch.scope_id,
                            obj.uid,
                            obj.revision_uid,
                            payload,
                            obj.lifecycle_state.value,
                            now,
                        ),
                        "payload_json",
                        payload,
                    )
                    for ref in obj.source_refs:
                        cur = self.connection.execute(
                            "INSERT OR IGNORE INTO object_revision_sources(domain,scope_id,revision_uid,raw_sha256,source_instance,source_object_id) VALUES (?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                obj.revision_uid,
                                ref.raw_payload_sha256,
                                ref.source_instance,
                                ref.source_object_id,
                            ),
                        )
                        changes += max(cur.rowcount, 0)
                        self.connection.execute(
                            "INSERT OR IGNORE INTO poll_observations(domain,scope_id,evidence_kind,revision_uid,raw_sha256,source_instance,source_snapshot_id,observed_at) VALUES (?,?,?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                "object",
                                obj.revision_uid,
                                ref.raw_payload_sha256,
                                ref.source_instance,
                                ref.source_snapshot_id,
                                now,
                            ),
                        )
                    for identifier in obj.external_ids:
                        cur = self.connection.execute(
                            "INSERT OR IGNORE INTO external_ids(domain,scope_id,namespace,value,object_uid,object_revision_uid,taxonomy,version) VALUES (?,?,?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                identifier.namespace,
                                identifier.value,
                                obj.uid,
                                obj.revision_uid,
                                identifier.taxonomy,
                                identifier.version,
                            ),
                        )
                        changes += max(cur.rowcount, 0)
                    if obj.lifecycle_state.value in {"deleted", "revoked"}:
                        cur = self.connection.execute(
                            "INSERT OR IGNORE INTO tombstones(domain,scope_id,evidence_kind,evidence_uid,revision_uid,reason,tombstoned_at) VALUES (?,?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                "object",
                                obj.uid,
                                obj.revision_uid,
                                (
                                    "upstream_deleted"
                                    if obj.lifecycle_state.value == "deleted"
                                    else "revoked"
                                ),
                                now,
                            ),
                        )
                        changes += max(cur.rowcount, 0)

                for relation in batch.relations:
                    if relation.domain != batch.domain or relation.scope_id != batch.scope_id:
                        raise ForeignKeyMismatch("relation domain/scope does not match batch")
                    cur = self.connection.execute(
                        "INSERT OR IGNORE INTO relations(domain,scope_id,relation_uid,source_object_uid,target_object_uid) VALUES (?,?,?,?,?)",
                        (
                            batch.domain,
                            batch.scope_id,
                            relation.uid,
                            relation.source_object_uid,
                            relation.target_object_uid,
                        ),
                    )
                    changes += max(cur.rowcount, 0)
                    payload = _semantic_payload(relation)
                    changes += self._insert_or_verify(
                        "relation_revisions",
                        "domain=? AND scope_id=? AND revision_uid=?",
                        (batch.domain, batch.scope_id, relation.revision_uid),
                        "INSERT INTO relation_revisions(domain,scope_id,relation_uid,revision_uid,payload_json,assertion_kind,lifecycle_state,created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (
                            batch.domain,
                            batch.scope_id,
                            relation.uid,
                            relation.revision_uid,
                            payload,
                            relation.assertion_kind,
                            relation.lifecycle_state.value,
                            now,
                        ),
                        "payload_json",
                        payload,
                    )
                    for ref in relation.evidence_refs:
                        cur = self.connection.execute(
                            "INSERT OR IGNORE INTO relation_revision_sources(domain,scope_id,revision_uid,raw_sha256,source_instance,source_object_id) VALUES (?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                relation.revision_uid,
                                ref.raw_payload_sha256,
                                ref.source_instance,
                                ref.source_object_id,
                            ),
                        )
                        changes += max(cur.rowcount, 0)
                        self.connection.execute(
                            "INSERT OR IGNORE INTO poll_observations(domain,scope_id,evidence_kind,revision_uid,raw_sha256,source_instance,source_snapshot_id,observed_at) VALUES (?,?,?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                "relation",
                                relation.revision_uid,
                                ref.raw_payload_sha256,
                                ref.source_instance,
                                ref.source_snapshot_id,
                                now,
                            ),
                        )
                    if relation.lifecycle_state.value in {"deleted", "revoked"}:
                        cur = self.connection.execute(
                            "INSERT OR IGNORE INTO tombstones(domain,scope_id,evidence_kind,evidence_uid,revision_uid,reason,tombstoned_at) VALUES (?,?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                "relation",
                                relation.uid,
                                relation.revision_uid,
                                (
                                    "upstream_deleted"
                                    if relation.lifecycle_state.value == "deleted"
                                    else "revoked"
                                ),
                                now,
                            ),
                        )
                        changes += max(cur.rowcount, 0)
                    if relation.assertion_kind == "cross_source_equivalence":
                        cur = self.connection.execute(
                            "INSERT OR IGNORE INTO evidence_equivalences(domain,scope_id,relation_revision_uid,source_object_uid,target_object_uid,created_at) VALUES (?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                relation.revision_uid,
                                relation.source_object_uid,
                                relation.target_object_uid,
                                now,
                            ),
                        )
                        changes += max(cur.rowcount, 0)

                for chunk in batch.chunks:
                    if chunk.domain != batch.domain or chunk.scope_id != batch.scope_id:
                        raise ForeignKeyMismatch("chunk domain/scope does not match batch")
                    payload = _semantic_payload(chunk)
                    row = self.connection.execute(
                        "SELECT payload_json FROM chunks WHERE domain=? AND scope_id=? AND chunk_uid=?",
                        (batch.domain, batch.scope_id, chunk.uid),
                    ).fetchone()
                    if row is not None and row["payload_json"] != payload:
                        raise ImmutableRevisionConflict("conflicting immutable chunk")
                    if row is None:
                        self.connection.execute(
                            "INSERT INTO chunks(domain,scope_id,chunk_uid,object_uid,object_revision_uid,payload_json,created_at) VALUES (?,?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                chunk.uid,
                                chunk.object_uid,
                                chunk.object_revision_uid,
                                payload,
                                now,
                            ),
                        )
                        changes += 1
                    for ref in chunk.source_refs:
                        cur = self.connection.execute(
                            "INSERT OR IGNORE INTO chunk_sources(domain,scope_id,chunk_uid,raw_sha256,source_instance,source_object_id) VALUES (?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                chunk.uid,
                                ref.raw_payload_sha256,
                                ref.source_instance,
                                ref.source_object_id,
                            ),
                        )
                        changes += max(cur.rowcount, 0)

                if snapshot is not None:
                    row = self.connection.execute(
                        "SELECT manifest_sha256,active FROM snapshots WHERE domain=? AND scope_id=? AND snapshot_id=?",
                        (batch.domain, batch.scope_id, snapshot.snapshot_id),
                    ).fetchone()
                    if row is not None and row["manifest_sha256"] != snapshot.manifest_sha256:
                        raise ImmutableRevisionConflict(
                            "snapshot id already exists with a different manifest"
                        )
                    if row is None:
                        self.connection.execute(
                            "INSERT INTO snapshots(domain,scope_id,snapshot_id,manifest_sha256,active,created_at) VALUES (?,?,?,?,0,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                snapshot.snapshot_id,
                                snapshot.manifest_sha256,
                                now,
                            ),
                        )
                        changes += 1
                    for obj in batch.objects:
                        cur = self.connection.execute(
                            "INSERT OR IGNORE INTO snapshot_membership(domain,scope_id,snapshot_id,evidence_kind,evidence_uid,revision_uid) VALUES (?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                snapshot.snapshot_id,
                                "object",
                                obj.uid,
                                obj.revision_uid,
                            ),
                        )
                        changes += max(cur.rowcount, 0)
                    for relation in batch.relations:
                        cur = self.connection.execute(
                            "INSERT OR IGNORE INTO snapshot_membership(domain,scope_id,snapshot_id,evidence_kind,evidence_uid,revision_uid) VALUES (?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                snapshot.snapshot_id,
                                "relation",
                                relation.uid,
                                relation.revision_uid,
                            ),
                        )
                        changes += max(cur.rowcount, 0)
                    for chunk in batch.chunks:
                        cur = self.connection.execute(
                            "INSERT OR IGNORE INTO snapshot_membership(domain,scope_id,snapshot_id,evidence_kind,evidence_uid,revision_uid) VALUES (?,?,?,?,?,?)",
                            (
                                batch.domain,
                                batch.scope_id,
                                snapshot.snapshot_id,
                                "chunk",
                                chunk.uid,
                                chunk.uid,
                            ),
                        )
                        changes += max(cur.rowcount, 0)

                if checkpoint is not None:
                    cursor_json = canonical_json(dict(checkpoint.cursor))
                    self.connection.execute(
                        "INSERT INTO checkpoints(domain,scope_id,source_instance,cursor_json,updated_at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(domain,scope_id,source_instance) DO UPDATE SET cursor_json=excluded.cursor_json,updated_at=excluded.updated_at",
                        (
                            batch.domain,
                            batch.scope_id,
                            checkpoint.source_instance,
                            cursor_json,
                            now,
                        ),
                    )
                self.connection.commit()
            except sqlite3.IntegrityError as exc:
                self.connection.rollback()
                raise ForeignKeyMismatch(str(exc)) from exc
            except Exception:
                self.connection.rollback()
                raise

            return PersistResult(
                logical_changes=changes,
                raw_payloads_written=len(resolved_raw),
                objects_seen=len(batch.objects),
                relations_seen=len(batch.relations),
                chunks_seen=len(batch.chunks),
            )

    def _sources_for_revision(
        self, kind: str, domain: str, scope_id: str, revision_uid: str
    ) -> list[dict[str, Any]]:
        table = "object_revision_sources" if kind == "object" else "relation_revision_sources"
        return [
            dict(row)
            for row in self.connection.execute(
                f"SELECT raw_sha256,source_instance,source_object_id FROM {table} "
                "WHERE domain=? AND scope_id=? AND revision_uid=? "
                "ORDER BY source_instance,source_object_id,raw_sha256",
                (domain, scope_id, revision_uid),
            )
        ]

    def get_revision(self, domain: str, scope_id: str, revision_uid: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT object_uid AS evidence_uid,payload_json FROM object_revisions WHERE domain=? AND scope_id=? AND revision_uid=?",
            (domain, scope_id, revision_uid),
        ).fetchone()
        kind = "object"
        if row is None:
            row = self.connection.execute(
                "SELECT relation_uid AS evidence_uid,payload_json FROM relation_revisions WHERE domain=? AND scope_id=? AND revision_uid=?",
                (domain, scope_id, revision_uid),
            ).fetchone()
            kind = "relation"
        if row is None:
            return None
        return {
            "kind": kind,
            "domain": domain,
            "scope_id": scope_id,
            "evidence_uid": row["evidence_uid"],
            "revision_uid": revision_uid,
            "payload": json.loads(row["payload_json"]),
            "sources": self._sources_for_revision(kind, domain, scope_id, revision_uid),
        }

    def list_scoped_revisions(self, domain: str, scope_id: str) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        for table, kind, id_column in (
            ("object_revisions", "object", "object_uid"),
            ("relation_revisions", "relation", "relation_uid"),
        ):
            for row in self.connection.execute(
                f"SELECT {id_column} AS evidence_uid,revision_uid FROM {table} "
                "WHERE domain=? AND scope_id=? ORDER BY revision_uid",
                (domain, scope_id),
            ):
                rows.append(
                    {"kind": kind, "evidence_uid": row["evidence_uid"], "revision_uid": row["revision_uid"]}
                )
        return tuple(sorted(rows, key=lambda item: (item["kind"], item["revision_uid"])))

    def get_assertion(self, domain: str, scope_id: str, revision_uid: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT relation_uid,payload_json FROM relation_revisions WHERE domain=? AND scope_id=? AND revision_uid=?",
            (domain, scope_id, revision_uid),
        ).fetchone()
        if row is None:
            return None
        return {
            "relation_uid": row["relation_uid"],
            "revision_uid": revision_uid,
            "payload": json.loads(row["payload_json"]),
            "sources": self._sources_for_revision("relation", domain, scope_id, revision_uid),
        }

    def get_chunk(self, domain: str, scope_id: str, chunk_uid: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT payload_json FROM chunks WHERE domain=? AND scope_id=? AND chunk_uid=?",
            (domain, scope_id, chunk_uid),
        ).fetchone()
        if row is None:
            return None
        sources = [
            dict(item)
            for item in self.connection.execute(
                "SELECT raw_sha256,source_instance,source_object_id FROM chunk_sources "
                "WHERE domain=? AND scope_id=? AND chunk_uid=?",
                (domain, scope_id, chunk_uid),
            )
        ]
        return {"chunk_uid": chunk_uid, "payload": json.loads(row["payload_json"]), "sources": sources}

    def resolve_external_ids(
        self, domain: str, scope_id: str, namespace: str, value: str
    ) -> tuple[dict[str, Any], ...]:
        rows = self.connection.execute(
            "SELECT object_uid,object_revision_uid,taxonomy,version FROM external_ids "
            "WHERE domain=? AND scope_id=? AND namespace=? AND value=? ORDER BY object_revision_uid",
            (domain, scope_id, namespace, value),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def get_checkpoint(self, domain: str, scope_id: str, source_instance: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT cursor_json FROM checkpoints WHERE domain=? AND scope_id=? AND source_instance=?",
            (domain, scope_id, source_instance),
        ).fetchone()
        return None if row is None else json.loads(row["cursor_json"])

    def get_snapshot(self, domain: str, scope_id: str, snapshot_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT manifest_sha256,active FROM snapshots WHERE domain=? AND scope_id=? AND snapshot_id=?",
            (domain, scope_id, snapshot_id),
        ).fetchone()
        return None if row is None else {
            "manifest_sha256": row["manifest_sha256"],
            "active": bool(row["active"]),
        }

    def _authorize_raw_link(
        self,
        digest: str,
        *,
        scope: ResolvedScope,
        policy: RetrievalPolicy,
        view: AuthorizedEvidenceView,
        destination: str,
    ) -> sqlite3.Row:
        decision = policy.authorize_evidence(view, scope, destination)
        require_authorized(decision)
        if view.domain != scope.domain or view.scope_id != scope.scope_id:
            raise PermissionError("raw payload is not authorized for this evidence view")
        sql = """
        SELECT rp.byte_length FROM raw_payloads rp
        WHERE rp.domain=? AND rp.scope_id=? AND rp.sha256=? AND EXISTS (
          SELECT 1 FROM object_revision_sources s
          JOIN object_revisions r ON r.domain=s.domain AND r.scope_id=s.scope_id AND r.revision_uid=s.revision_uid
          WHERE s.domain=rp.domain AND s.scope_id=rp.scope_id AND s.raw_sha256=rp.sha256
            AND (r.object_uid=? OR r.revision_uid=?)
          UNION ALL
          SELECT 1 FROM relation_revision_sources s
          JOIN relation_revisions r ON r.domain=s.domain AND r.scope_id=s.scope_id AND r.revision_uid=s.revision_uid
          WHERE s.domain=rp.domain AND s.scope_id=rp.scope_id AND s.raw_sha256=rp.sha256
            AND (r.relation_uid=? OR r.revision_uid=?)
          UNION ALL
          SELECT 1 FROM chunk_sources s
          WHERE s.domain=rp.domain AND s.scope_id=rp.scope_id AND s.raw_sha256=rp.sha256
            AND s.chunk_uid=?
        )
        """
        row = self.connection.execute(
            sql,
            (
                scope.domain,
                scope.scope_id,
                digest,
                view.evidence_uid,
                view.evidence_uid,
                view.evidence_uid,
                view.evidence_uid,
                view.evidence_uid,
            ),
        ).fetchone()
        if row is None:
            raise PermissionError("raw payload is not authorized for this evidence view")
        return row

    def raw_metadata(
        self,
        digest: str,
        *,
        scope: ResolvedScope,
        policy: RetrievalPolicy,
        view: AuthorizedEvidenceView,
        destination: str = "caller",
    ) -> dict[str, Any]:
        row = self._authorize_raw_link(
            digest, scope=scope, policy=policy, view=view, destination=destination
        )
        return {"sha256": digest, "byte_length": int(row["byte_length"])}

    def hydrate_raw(
        self,
        digest: str,
        *,
        scope: ResolvedScope,
        policy: RetrievalPolicy,
        view: AuthorizedEvidenceView,
        destination: str = "caller",
    ) -> bytes:
        self._authorize_raw_link(
            digest, scope=scope, policy=policy, view=view, destination=destination
        )
        return self.raw_store.read(digest)
