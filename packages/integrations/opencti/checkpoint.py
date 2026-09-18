"""Durable at-least-once OpenCTI capture checkpoints and replay ledger."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from packages.evidence.ids import canonical_hash, canonical_json
from packages.evidence.store import EvidenceStore, ImmutableRevisionConflict

from .reader import CapturePage, raw_payload_bytes


CHECKPOINT_SCHEMA_VERSION = 1
_CAPTURE_NORMALIZER = "opencti-capture-ledger-v1"


class OpenCTICheckpointError(RuntimeError):
    pass


class CheckpointNamespaceMismatch(OpenCTICheckpointError):
    pass


class ReplayPageConflict(OpenCTICheckpointError):
    pass


@dataclass(frozen=True)
class CheckpointKey:
    source_instance: str
    domain: str
    scope_id: str
    supported_type: str
    filter_fingerprint: str

    @classmethod
    def create(
        cls,
        *,
        source_instance: str,
        domain: str,
        scope_id: str,
        supported_type: str,
        filters: Mapping[str, Any] | None,
    ) -> "CheckpointKey":
        return cls(
            source_instance=source_instance,
            domain=domain,
            scope_id=scope_id,
            supported_type=supported_type,
            filter_fingerprint=filter_fingerprint(supported_type, filters),
        )

    @property
    def values(self) -> tuple[str, str, str, str, str]:
        return (
            self.source_instance,
            self.domain,
            self.scope_id,
            self.supported_type,
            self.filter_fingerprint,
        )


@dataclass(frozen=True)
class ReplayCheckpoint:
    key: CheckpointKey
    active_run_id: str | None
    state: str
    ingestion_cursor: dict[str, Any] | None
    published_cursor: dict[str, Any] | None
    scan_bounds: dict[str, Any]
    page_count: int
    completed_pages: int
    last_tiebreak_id: str | None
    source_version: str
    generation_id: str | None
    retry_count: int
    next_retry_at: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def filter_fingerprint(
    supported_type: str,
    filters: Mapping[str, Any] | None,
) -> str:
    return canonical_hash(
        ["opencti-filter-v1", supported_type, dict(filters or {})]
    )


def _migration(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS opencti_checkpoint_schema_migrations(
          version INTEGER PRIMARY KEY,
          applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS opencti_checkpoints(
          source_instance TEXT NOT NULL,
          domain TEXT NOT NULL,
          scope_id TEXT NOT NULL,
          supported_type TEXT NOT NULL,
          filter_fingerprint TEXT NOT NULL,
          active_run_id TEXT,
          state TEXT NOT NULL CHECK(
            state IN (
              'idle','capturing','captured','publishing',
              'published','failed','needs_full_rescan'
            )
          ),
          ingestion_cursor_json TEXT,
          published_cursor_json TEXT,
          scan_bounds_json TEXT NOT NULL,
          page_count INTEGER NOT NULL DEFAULT 0 CHECK(page_count >= 0),
          completed_pages INTEGER NOT NULL DEFAULT 0 CHECK(completed_pages >= 0),
          last_tiebreak_id TEXT,
          source_version TEXT NOT NULL,
          generation_id TEXT,
          retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
          next_retry_at TEXT,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(
            source_instance,domain,scope_id,supported_type,filter_fingerprint
          )
        );
        CREATE TABLE IF NOT EXISTS opencti_ingestion_jobs(
          source_instance TEXT NOT NULL,
          domain TEXT NOT NULL,
          scope_id TEXT NOT NULL,
          supported_type TEXT NOT NULL,
          filter_fingerprint TEXT NOT NULL,
          run_id TEXT NOT NULL,
          job_id TEXT NOT NULL,
          status TEXT NOT NULL CHECK(
            status IN ('capturing','captured','publishing','published','failed')
          ),
          page_count INTEGER NOT NULL DEFAULT 0 CHECK(page_count >= 0),
          records_sha256 TEXT,
          generation_id TEXT,
          error_code TEXT,
          retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
          requested_at TEXT NOT NULL,
          completed_at TEXT,
          PRIMARY KEY(
            source_instance,domain,scope_id,supported_type,
            filter_fingerprint,run_id
          ),
          UNIQUE(job_id)
        );
        CREATE TABLE IF NOT EXISTS opencti_ingestion_pages(
          source_instance TEXT NOT NULL,
          domain TEXT NOT NULL,
          scope_id TEXT NOT NULL,
          supported_type TEXT NOT NULL,
          filter_fingerprint TEXT NOT NULL,
          run_id TEXT NOT NULL,
          page_index INTEGER NOT NULL CHECK(page_index >= 0),
          cursor_before TEXT,
          cursor_after TEXT,
          has_next_page INTEGER NOT NULL CHECK(has_next_page IN (0,1)),
          global_count INTEGER,
          record_count INTEGER NOT NULL CHECK(record_count >= 0),
          records_sha256 TEXT NOT NULL,
          captured_at TEXT NOT NULL,
          PRIMARY KEY(
            source_instance,domain,scope_id,supported_type,
            filter_fingerprint,run_id,page_index
          )
        );
        CREATE TABLE IF NOT EXISTS opencti_ingestion_records(
          source_instance TEXT NOT NULL,
          domain TEXT NOT NULL,
          scope_id TEXT NOT NULL,
          supported_type TEXT NOT NULL,
          filter_fingerprint TEXT NOT NULL,
          run_id TEXT NOT NULL,
          page_index INTEGER NOT NULL,
          source_object_id TEXT NOT NULL,
          raw_sha256 TEXT NOT NULL,
          source_version TEXT,
          PRIMARY KEY(
            source_instance,domain,scope_id,supported_type,
            filter_fingerprint,run_id,page_index,source_object_id,raw_sha256
          ),
          FOREIGN KEY(domain,scope_id,raw_sha256)
            REFERENCES raw_payloads(domain,scope_id,sha256) ON DELETE RESTRICT
        );
        """
    )
    row = connection.execute(
        "SELECT MAX(version) FROM opencti_checkpoint_schema_migrations"
    ).fetchone()
    current = int(row[0] or 0)
    if current > CHECKPOINT_SCHEMA_VERSION:
        raise OpenCTICheckpointError(
            f"checkpoint schema {current} is newer than supported"
        )
    if current == 0:
        connection.execute(
            "INSERT INTO opencti_checkpoint_schema_migrations(version,applied_at) "
            "VALUES(?,?)",
            (CHECKPOINT_SCHEMA_VERSION, _now()),
        )


class OpenCTICheckpointLedger:
    """Replay-safe page ledger backed by the existing evidence catalog."""

    def __init__(self, store: EvidenceStore) -> None:
        self.store = store
        self.db = store.connection
        with store.writer_lock():
            _migration(self.db)

    @staticmethod
    def job_id(key: CheckpointKey, run_id: str) -> str:
        return canonical_hash(["opencti-ingestion-job-v1", *key.values, run_id])

    def get(self, key: CheckpointKey) -> ReplayCheckpoint | None:
        row = self.db.execute(
            """
            SELECT * FROM opencti_checkpoints
            WHERE source_instance=? AND domain=? AND scope_id=?
              AND supported_type=? AND filter_fingerprint=?
            """,
            key.values,
        ).fetchone()
        if row is None:
            return None
        return ReplayCheckpoint(
            key=key,
            active_run_id=row["active_run_id"],
            state=row["state"],
            ingestion_cursor=(
                None
                if row["ingestion_cursor_json"] is None
                else json.loads(row["ingestion_cursor_json"])
            ),
            published_cursor=(
                None
                if row["published_cursor_json"] is None
                else json.loads(row["published_cursor_json"])
            ),
            scan_bounds=json.loads(row["scan_bounds_json"]),
            page_count=int(row["page_count"]),
            completed_pages=int(row["completed_pages"]),
            last_tiebreak_id=row["last_tiebreak_id"],
            source_version=row["source_version"],
            generation_id=row["generation_id"],
            retry_count=int(row["retry_count"]),
            next_retry_at=row["next_retry_at"],
        )

    def begin_run(
        self,
        key: CheckpointKey,
        *,
        run_id: str,
        source_version: str,
        scan_bounds: Mapping[str, Any],
    ) -> None:
        now = _now()
        with self.store.writer_lock():
            try:
                self.db.execute("BEGIN IMMEDIATE")
                existing = self.get(key)
                if (
                    existing is not None
                    and existing.state == "capturing"
                    and existing.active_run_id != run_id
                ):
                    self.db.execute(
                        """
                        UPDATE opencti_ingestion_jobs
                        SET status='failed',error_code='interrupted-full-rescan',
                            completed_at=?
                        WHERE source_instance=? AND domain=? AND scope_id=?
                          AND supported_type=? AND filter_fingerprint=?
                          AND run_id=? AND status='capturing'
                        """,
                        (now, *key.values, existing.active_run_id),
                    )
                self.db.execute(
                    """
                    INSERT INTO opencti_checkpoints(
                      source_instance,domain,scope_id,supported_type,
                      filter_fingerprint,active_run_id,state,
                      ingestion_cursor_json,published_cursor_json,
                      scan_bounds_json,page_count,completed_pages,
                      last_tiebreak_id,source_version,generation_id,
                      retry_count,next_retry_at,updated_at
                    ) VALUES(?,?,?,?,?,?,'capturing',NULL,NULL,?,0,0,NULL,?,
                             NULL,0,NULL,?)
                    ON CONFLICT(
                      source_instance,domain,scope_id,supported_type,
                      filter_fingerprint
                    ) DO UPDATE SET
                      active_run_id=excluded.active_run_id,
                      state='capturing',
                      ingestion_cursor_json=NULL,
                      scan_bounds_json=excluded.scan_bounds_json,
                      page_count=0,
                      completed_pages=0,
                      last_tiebreak_id=NULL,
                      source_version=excluded.source_version,
                      generation_id=NULL,
                      retry_count=0,
                      next_retry_at=NULL,
                      updated_at=excluded.updated_at
                    """,
                    (
                        *key.values,
                        run_id,
                        canonical_json(dict(scan_bounds)),
                        source_version,
                        now,
                    ),
                )
                self.db.execute(
                    """
                    INSERT OR IGNORE INTO opencti_ingestion_jobs(
                      source_instance,domain,scope_id,supported_type,
                      filter_fingerprint,run_id,job_id,status,
                      requested_at
                    ) VALUES(?,?,?,?,?,?,?,'capturing',?)
                    """,
                    (*key.values, run_id, self.job_id(key, run_id), now),
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def record_page(
        self,
        key: CheckpointKey,
        *,
        run_id: str,
        page: CapturePage,
    ) -> None:
        if page.kind != key.supported_type:
            raise CheckpointNamespaceMismatch("page type differs from checkpoint key")
        if page.source_instance != key.source_instance:
            raise CheckpointNamespaceMismatch(
                "page source instance differs from checkpoint key"
            )
        if filter_fingerprint(page.kind, page.filters) != key.filter_fingerprint:
            raise CheckpointNamespaceMismatch(
                "page filter fingerprint differs from checkpoint key"
            )

        raw_items: list[tuple[Any, bytes]] = []
        for record in page.records:
            raw = raw_payload_bytes(record)
            self.store.raw_store.put(raw, expected_sha256=record.raw_payload.sha256)
            raw_items.append((record, raw))

        record_manifest = [
            [
                record.source_object_id,
                record.raw_payload.sha256,
                record.payload.get("modified"),
                record.payload.get("updated_at"),
            ]
            for record, _ in raw_items
        ]
        records_digest = canonical_hash(
            ["opencti-ingestion-page-v1", page.kind, page.page_index, record_manifest]
        )
        cursor = {
            "after": page.cursor_after,
            "page_index": page.page_index,
            "has_next_page": page.has_next_page,
        }
        last_id = max(
            (record.source_object_id for record, _ in raw_items),
            default=None,
        )
        now = _now()

        with self.store.writer_lock():
            try:
                self.db.execute("BEGIN IMMEDIATE")
                state = self.get(key)
                if (
                    state is None
                    or state.active_run_id != run_id
                    or state.state != "capturing"
                ):
                    raise OpenCTICheckpointError(
                        "page belongs to a non-active ingestion run"
                    )
                existing = self.db.execute(
                    """
                    SELECT records_sha256 FROM opencti_ingestion_pages
                    WHERE source_instance=? AND domain=? AND scope_id=?
                      AND supported_type=? AND filter_fingerprint=?
                      AND run_id=? AND page_index=?
                    """,
                    (*key.values, run_id, page.page_index),
                ).fetchone()
                if existing is not None and existing["records_sha256"] != records_digest:
                    raise ReplayPageConflict(
                        "same replay page index has different content"
                    )

                for record, raw in raw_items:
                    self.db.execute(
                        """
                        INSERT OR IGNORE INTO raw_payloads(
                          domain,scope_id,sha256,byte_length,created_at
                        ) VALUES(?,?,?,?,?)
                        """,
                        (
                            key.domain,
                            key.scope_id,
                            record.raw_payload.sha256,
                            len(raw),
                            now,
                        ),
                    )
                    self.db.execute(
                        """
                        INSERT OR IGNORE INTO raw_payload_sources(
                          domain,scope_id,sha256,source_instance,
                          source_object_id,normalizer_version,
                          source_snapshot_id,upstream_origin,source_uri
                        ) VALUES(?,?,?,?,?,?,?,?,NULL)
                        """,
                        (
                            key.domain,
                            key.scope_id,
                            record.raw_payload.sha256,
                            key.source_instance,
                            record.source_object_id,
                            _CAPTURE_NORMALIZER,
                            run_id,
                            f"opencti:{key.supported_type}",
                        ),
                    )
                    source_version = (
                        record.payload.get("modified")
                        or record.payload.get("updated_at")
                    )
                    self.db.execute(
                        """
                        INSERT OR IGNORE INTO opencti_ingestion_records(
                          source_instance,domain,scope_id,supported_type,
                          filter_fingerprint,run_id,page_index,
                          source_object_id,raw_sha256,source_version
                        ) VALUES(?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            *key.values,
                            run_id,
                            page.page_index,
                            record.source_object_id,
                            record.raw_payload.sha256,
                            None if source_version is None else str(source_version),
                        ),
                    )

                self.db.execute(
                    """
                    INSERT OR IGNORE INTO opencti_ingestion_pages(
                      source_instance,domain,scope_id,supported_type,
                      filter_fingerprint,run_id,page_index,
                      cursor_before,cursor_after,has_next_page,global_count,
                      record_count,records_sha256,captured_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        *key.values,
                        run_id,
                        page.page_index,
                        page.cursor_before,
                        page.cursor_after,
                        1 if page.has_next_page else 0,
                        page.global_count,
                        len(page.records),
                        records_digest,
                        page.capture_completed_at,
                    ),
                )
                # Job/page receipt and cursor advancement are one transaction.
                self.db.execute(
                    """
                    UPDATE opencti_ingestion_jobs
                    SET page_count=(
                      SELECT COUNT(*) FROM opencti_ingestion_pages
                      WHERE source_instance=? AND domain=? AND scope_id=?
                        AND supported_type=? AND filter_fingerprint=?
                        AND run_id=?
                    )
                    WHERE source_instance=? AND domain=? AND scope_id=?
                      AND supported_type=? AND filter_fingerprint=?
                      AND run_id=?
                    """,
                    (*key.values, run_id, *key.values, run_id),
                )
                self.db.execute(
                    """
                    UPDATE opencti_checkpoints
                    SET ingestion_cursor_json=?,
                        page_count=MAX(page_count, ?),
                        completed_pages=(
                          SELECT COUNT(*) FROM opencti_ingestion_pages
                          WHERE source_instance=? AND domain=? AND scope_id=?
                            AND supported_type=? AND filter_fingerprint=?
                            AND run_id=?
                        ),
                        last_tiebreak_id=COALESCE(?,last_tiebreak_id),
                        updated_at=?
                    WHERE source_instance=? AND domain=? AND scope_id=?
                      AND supported_type=? AND filter_fingerprint=?
                      AND active_run_id=?
                    """,
                    (
                        canonical_json(cursor),
                        page.page_index + 1,
                        *key.values,
                        run_id,
                        last_id,
                        now,
                        *key.values,
                        run_id,
                    ),
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def mark_capture_complete(
        self,
        key: CheckpointKey,
        *,
        run_id: str,
        scan_bounds: Mapping[str, Any],
    ) -> None:
        with self.store.writer_lock():
            self.db.execute(
                """
                UPDATE opencti_checkpoints
                SET state='captured',scan_bounds_json=?,updated_at=?
                WHERE source_instance=? AND domain=? AND scope_id=?
                  AND supported_type=? AND filter_fingerprint=?
                  AND active_run_id=? AND state='capturing'
                """,
                (canonical_json(dict(scan_bounds)), _now(), *key.values, run_id),
            )
            self.db.execute(
                """
                UPDATE opencti_ingestion_jobs
                SET status='captured'
                WHERE source_instance=? AND domain=? AND scope_id=?
                  AND supported_type=? AND filter_fingerprint=?
                  AND run_id=? AND status='capturing'
                """,
                (*key.values, run_id),
            )

    def bind_generation(
        self,
        keys: tuple[CheckpointKey, ...],
        *,
        run_id: str,
        generation_id: str,
    ) -> None:
        with self.store.writer_lock():
            try:
                self.db.execute("BEGIN IMMEDIATE")
                for key in keys:
                    self.db.execute(
                        """
                        UPDATE opencti_checkpoints
                        SET state='publishing',generation_id=?,updated_at=?
                        WHERE source_instance=? AND domain=? AND scope_id=?
                          AND supported_type=? AND filter_fingerprint=?
                          AND active_run_id=? AND state='captured'
                        """,
                        (generation_id, _now(), *key.values, run_id),
                    )
                    self.db.execute(
                        """
                        UPDATE opencti_ingestion_jobs
                        SET status='publishing',generation_id=?
                        WHERE source_instance=? AND domain=? AND scope_id=?
                          AND supported_type=? AND filter_fingerprint=?
                          AND run_id=? AND status='captured'
                        """,
                        (generation_id, *key.values, run_id),
                    )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def mark_published(
        self,
        keys: tuple[CheckpointKey, ...],
        *,
        run_id: str,
        generation_id: str,
        corpus_id: str,
    ) -> None:
        now = _now()
        with self.store.writer_lock():
            try:
                self.db.execute("BEGIN IMMEDIATE")
                for key in keys:
                    active = self.db.execute(
                        """
                        SELECT generation_id FROM active_generations
                        WHERE domain=? AND scope_id=? AND corpus_id=?
                        """,
                        (key.domain, key.scope_id, corpus_id),
                    ).fetchone()
                    if active is None or active["generation_id"] != generation_id:
                        raise OpenCTICheckpointError(
                            "published cursor cannot advance before generation activation"
                        )
                    self.db.execute(
                        """
                        UPDATE opencti_checkpoints
                        SET state='published',
                            published_cursor_json=ingestion_cursor_json,
                            generation_id=?,retry_count=0,next_retry_at=NULL,
                            updated_at=?
                        WHERE source_instance=? AND domain=? AND scope_id=?
                          AND supported_type=? AND filter_fingerprint=?
                          AND active_run_id=?
                        """,
                        (generation_id, now, *key.values, run_id),
                    )
                    self.db.execute(
                        """
                        UPDATE opencti_ingestion_jobs
                        SET status='published',generation_id=?,
                            completed_at=?,error_code=NULL
                        WHERE source_instance=? AND domain=? AND scope_id=?
                          AND supported_type=? AND filter_fingerprint=?
                          AND run_id=?
                        """,
                        (generation_id, now, *key.values, run_id),
                    )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def reconcile_activated(self, *, corpus_id: str) -> int:
        rows = self.db.execute(
            """
            SELECT source_instance,domain,scope_id,supported_type,
                   filter_fingerprint,run_id,generation_id
            FROM opencti_ingestion_jobs
            WHERE generation_id IS NOT NULL
              AND status IN ('captured','publishing','failed')
            ORDER BY requested_at
            """
        ).fetchall()
        reconciled = 0
        for row in rows:
            active = self.db.execute(
                """
                SELECT generation_id FROM active_generations
                WHERE domain=? AND scope_id=? AND corpus_id=?
                """,
                (row["domain"], row["scope_id"], corpus_id),
            ).fetchone()
            if active is None or active["generation_id"] != row["generation_id"]:
                continue
            key = CheckpointKey(
                source_instance=row["source_instance"],
                domain=row["domain"],
                scope_id=row["scope_id"],
                supported_type=row["supported_type"],
                filter_fingerprint=row["filter_fingerprint"],
            )
            self.mark_published(
                (key,),
                run_id=row["run_id"],
                generation_id=row["generation_id"],
                corpus_id=corpus_id,
            )
            reconciled += 1
        return reconciled

    def fail_run(
        self,
        keys: tuple[CheckpointKey, ...],
        *,
        run_id: str,
        error_code: str,
    ) -> None:
        now_dt = datetime.now(timezone.utc)
        with self.store.writer_lock():
            try:
                self.db.execute("BEGIN IMMEDIATE")
                for key in keys:
                    row = self.db.execute(
                        """
                        SELECT retry_count FROM opencti_checkpoints
                        WHERE source_instance=? AND domain=? AND scope_id=?
                          AND supported_type=? AND filter_fingerprint=?
                        """,
                        key.values,
                    ).fetchone()
                    retry = min(8, int(row["retry_count"] if row else 0) + 1)
                    delay = min(300, 2 ** retry)
                    next_retry = (now_dt + timedelta(seconds=delay)).isoformat().replace(
                        "+00:00", "Z"
                    )
                    self.db.execute(
                        """
                        UPDATE opencti_checkpoints
                        SET state='failed',retry_count=?,next_retry_at=?,
                            updated_at=?
                        WHERE source_instance=? AND domain=? AND scope_id=?
                          AND supported_type=? AND filter_fingerprint=?
                          AND active_run_id=?
                        """,
                        (
                            retry,
                            next_retry,
                            _now(),
                            *key.values,
                            run_id,
                        ),
                    )
                    self.db.execute(
                        """
                        UPDATE opencti_ingestion_jobs
                        SET status='failed',error_code=?,retry_count=?,
                            completed_at=?
                        WHERE source_instance=? AND domain=? AND scope_id=?
                          AND supported_type=? AND filter_fingerprint=?
                          AND run_id=?
                        """,
                        (
                            error_code,
                            retry,
                            _now(),
                            *key.values,
                            run_id,
                        ),
                    )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def request_full_rescan(
        self,
        key: CheckpointKey,
        *,
        reason: str,
    ) -> None:
        with self.store.writer_lock():
            self.db.execute(
                """
                UPDATE opencti_checkpoints
                SET state='needs_full_rescan',
                    ingestion_cursor_json=NULL,
                    last_tiebreak_id=NULL,
                    updated_at=?
                WHERE source_instance=? AND domain=? AND scope_id=?
                  AND supported_type=? AND filter_fingerprint=?
                """,
                (_now(), *key.values),
            )

    def page_count(self, key: CheckpointKey, *, run_id: str) -> int:
        return int(
            self.db.execute(
                """
                SELECT COUNT(*) FROM opencti_ingestion_pages
                WHERE source_instance=? AND domain=? AND scope_id=?
                  AND supported_type=? AND filter_fingerprint=?
                  AND run_id=?
                """,
                (*key.values, run_id),
            ).fetchone()[0]
        )


__all__ = [
    "CheckpointKey",
    "CheckpointNamespaceMismatch",
    "OpenCTICheckpointError",
    "OpenCTICheckpointLedger",
    "ReplayCheckpoint",
    "ReplayPageConflict",
    "filter_fingerprint",
]
