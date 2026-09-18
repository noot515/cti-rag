"""Live visibility, withdrawal, merge, and freshness authority."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Iterable, Mapping

from packages.evidence.ids import canonical_hash, canonical_json
from packages.evidence.policy import ResolvedScope
from packages.evidence.store import EvidenceStore


VISIBILITY_SCHEMA_VERSION = 1
TOMBSTONE_REASONS = frozenset(
    {"upstream_deleted", "revoked", "no_longer_visible", "unknown"}
)


class VisibilityError(PermissionError):
    pass


class VisibilityExpired(VisibilityError):
    pass


class InventoryReconciliationError(RuntimeError):
    pass


@dataclass(frozen=True)
class InventoryOutcome:
    run_id: str
    complete: bool
    authorized: bool
    page_count: int
    seen_count: int
    tombstones_written: int
    lease_expires_at: str | None


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise InventoryReconciliationError("visibility timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _migrate(db) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS visibility_schema_migrations(
          version INTEGER PRIMARY KEY,
          applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inventory_runs(
          run_id TEXT PRIMARY KEY,
          domain TEXT NOT NULL,
          scope_id TEXT NOT NULL,
          source_instance TEXT NOT NULL,
          supported_type TEXT NOT NULL,
          type_fingerprint TEXT NOT NULL,
          filter_fingerprint TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('complete','incomplete','unauthorized')),
          completeness_proof TEXT,
          page_count INTEGER NOT NULL CHECK(page_count >= 0),
          seen_count INTEGER NOT NULL CHECK(seen_count >= 0),
          seen_sha256 TEXT NOT NULL,
          capture_started_at TEXT NOT NULL,
          capture_completed_at TEXT NOT NULL,
          failure_reason TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inventory_seen(
          run_id TEXT NOT NULL,
          source_object_id TEXT NOT NULL,
          PRIMARY KEY(run_id,source_object_id),
          FOREIGN KEY(run_id) REFERENCES inventory_runs(run_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS visibility_leases(
          domain TEXT NOT NULL,
          scope_id TEXT NOT NULL,
          source_instance TEXT NOT NULL,
          supported_type TEXT NOT NULL,
          type_fingerprint TEXT NOT NULL,
          filter_fingerprint TEXT NOT NULL,
          inventory_run_id TEXT NOT NULL,
          last_success_at TEXT NOT NULL,
          max_staleness_seconds INTEGER NOT NULL CHECK(max_staleness_seconds > 0),
          expires_at TEXT NOT NULL,
          PRIMARY KEY(
            domain,scope_id,source_instance,supported_type,
            type_fingerprint,filter_fingerprint
          ),
          FOREIGN KEY(inventory_run_id) REFERENCES inventory_runs(run_id)
            ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_visibility_lease_scope
          ON visibility_leases(domain,scope_id,source_instance,supported_type);
        CREATE TABLE IF NOT EXISTS evidence_merge_mappings(
          domain TEXT NOT NULL,
          scope_id TEXT NOT NULL,
          source_object_uid TEXT NOT NULL,
          target_object_uid TEXT NOT NULL,
          source_instance TEXT NOT NULL,
          provenance_json TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
          created_at TEXT NOT NULL,
          PRIMARY KEY(
            domain,scope_id,source_object_uid,target_object_uid,source_instance
          ),
          FOREIGN KEY(domain,scope_id,source_object_uid)
            REFERENCES objects(domain,scope_id,object_uid) ON DELETE RESTRICT,
          FOREIGN KEY(domain,scope_id,target_object_uid)
            REFERENCES objects(domain,scope_id,object_uid) ON DELETE RESTRICT
        );
        """
    )
    row = db.execute(
        "SELECT MAX(version) FROM visibility_schema_migrations"
    ).fetchone()
    current = int(row[0] or 0)
    if current > VISIBILITY_SCHEMA_VERSION:
        raise InventoryReconciliationError(
            f"visibility schema {current} is newer than supported"
        )
    if current == 0:
        db.execute(
            "INSERT INTO visibility_schema_migrations(version,applied_at) "
            "VALUES(?,?)",
            (VISIBILITY_SCHEMA_VERSION, _iso(_now_dt())),
        )


class LifecycleAuthority:
    """Authoritative live overlay over immutable evidence/snapshot history."""

    def __init__(self, store: EvidenceStore) -> None:
        self.store = store
        self.db = store.connection
        with store.writer_lock():
            _migrate(self.db)

    def _source_rows(
        self,
        *,
        domain: str,
        scope_id: str,
        source_instance: str,
        supported_type: str,
    ) -> tuple[tuple[str, str, str, str], ...]:
        rows: list[tuple[str, str, str, str]] = []
        if supported_type == "relationship":
            source_rows = self.db.execute(
                """
                SELECT s.source_object_id,
                       r.relation_uid AS evidence_uid,r.revision_uid
                FROM relation_revision_sources s
                JOIN relation_revisions r
                  ON r.domain=s.domain AND r.scope_id=s.scope_id
                 AND r.revision_uid=s.revision_uid
                WHERE s.domain=? AND s.scope_id=? AND s.source_instance=?
                """,
                (domain, scope_id, source_instance),
            )
            return tuple(
                (
                    "relation",
                    str(row["source_object_id"]),
                    str(row["evidence_uid"]),
                    str(row["revision_uid"]),
                )
                for row in source_rows
            )

        expected_object_types = {
            "vulnerability": {"vulnerability"},
            "report": {"report"},
            "attack_pattern": {"attack-pattern", "technique"},
        }.get(supported_type)
        if expected_object_types is None:
            raise InventoryReconciliationError(
                f"unsupported inventory type: {supported_type}"
            )
        for row in self.db.execute(
            """
            SELECT s.source_object_id,r.object_uid AS evidence_uid,
                   r.revision_uid,r.payload_json
            FROM object_revision_sources s
            JOIN object_revisions r
              ON r.domain=s.domain AND r.scope_id=s.scope_id
             AND r.revision_uid=s.revision_uid
            WHERE s.domain=? AND s.scope_id=? AND s.source_instance=?
            """,
            (domain, scope_id, source_instance),
        ):
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError as exc:
                raise InventoryReconciliationError(
                    "stored object revision payload is not valid JSON"
                ) from exc
            if payload.get("object_type") not in expected_object_types:
                continue
            rows.append(
                (
                    "object",
                    str(row["source_object_id"]),
                    str(row["evidence_uid"]),
                    str(row["revision_uid"]),
                )
            )
        return tuple(rows)

    def _tombstone(
        self,
        *,
        domain: str,
        scope_id: str,
        evidence_kind: str,
        evidence_uid: str,
        revision_uid: str,
        reason: str,
        now: str,
    ) -> int:
        if reason not in TOMBSTONE_REASONS:
            raise InventoryReconciliationError(
                f"unsupported tombstone reason: {reason}"
            )
        cur = self.db.execute(
            """
            INSERT OR IGNORE INTO tombstones(
              domain,scope_id,evidence_kind,evidence_uid,
              revision_uid,reason,tombstoned_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                domain,
                scope_id,
                evidence_kind,
                evidence_uid,
                revision_uid,
                reason,
                now,
            ),
        )
        return max(cur.rowcount, 0)

    def record_inventory(
        self,
        *,
        domain: str,
        scope_id: str,
        source_instance: str,
        supported_type: str,
        type_fingerprint: str,
        filter_fingerprint: str,
        seen_source_ids: Iterable[str],
        current_revisions: Mapping[
            str, Iterable[tuple[str, str, str]]
        ],
        explicit_status: Mapping[str, str],
        complete: bool,
        authorized: bool,
        page_count: int,
        capture_started_at: str,
        capture_completed_at: str,
        max_staleness_seconds: int,
        failure_reason: str | None = None,
    ) -> InventoryOutcome:
        if page_count < 0 or max_staleness_seconds <= 0:
            raise ValueError("invalid inventory page count or staleness budget")
        _parse_iso(capture_started_at)
        completed_dt = _parse_iso(capture_completed_at)
        seen = tuple(sorted(set(str(item) for item in seen_source_ids)))
        seen_sha = canonical_hash(["inventory-seen-v1", seen])
        status = "complete" if complete and authorized else (
            "unauthorized" if not authorized else "incomplete"
        )
        completeness_proof = (
            canonical_hash(
                [
                    "inventory-complete-v1",
                    domain,
                    scope_id,
                    source_instance,
                    supported_type,
                    type_fingerprint,
                    filter_fingerprint,
                    page_count,
                    seen_sha,
                    capture_started_at,
                    capture_completed_at,
                ]
            )
            if status == "complete"
            else None
        )
        run_id = canonical_hash(
            [
                "inventory-run-v1",
                domain,
                scope_id,
                source_instance,
                supported_type,
                type_fingerprint,
                filter_fingerprint,
                capture_started_at,
                capture_completed_at,
                seen_sha,
                status,
            ]
        )
        now = _iso(_now_dt())
        lease_expiry: str | None = None
        tombstones = 0

        with self.store.writer_lock():
            try:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute(
                    """
                    INSERT OR IGNORE INTO inventory_runs(
                      run_id,domain,scope_id,source_instance,supported_type,
                      type_fingerprint,filter_fingerprint,status,
                      completeness_proof,page_count,seen_count,seen_sha256,
                      capture_started_at,capture_completed_at,failure_reason,
                      created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        domain,
                        scope_id,
                        source_instance,
                        supported_type,
                        type_fingerprint,
                        filter_fingerprint,
                        status,
                        completeness_proof,
                        page_count,
                        len(seen),
                        seen_sha,
                        capture_started_at,
                        capture_completed_at,
                        failure_reason,
                        now,
                    ),
                )
                for source_id in seen:
                    self.db.execute(
                        "INSERT OR IGNORE INTO inventory_seen(run_id,source_object_id) "
                        "VALUES(?,?)",
                        (run_id, source_id),
                    )

                if status == "complete":
                    prior = self._source_rows(
                        domain=domain,
                        scope_id=scope_id,
                        source_instance=source_instance,
                        supported_type=supported_type,
                    )
                    seen_set = set(seen)
                    normalized_current = {
                        source_id: set(values)
                        for source_id, values in current_revisions.items()
                    }
                    for kind, source_id, evidence_uid, revision_uid in prior:
                        reason: str | None = None
                        if source_id not in seen_set:
                            reason = "no_longer_visible"
                        elif source_id in explicit_status:
                            reason = explicit_status[source_id]
                        else:
                            current = normalized_current.get(source_id, set())
                            if current and (kind, evidence_uid, revision_uid) not in current:
                                reason = "no_longer_visible"
                            elif (kind, evidence_uid, revision_uid) in current:
                                # A reappearing current revision may recover from
                                # a prior visibility loss, but never from an
                                # explicit revoke/deletion.
                                self.db.execute(
                                    """
                                    DELETE FROM tombstones
                                    WHERE domain=? AND scope_id=?
                                      AND evidence_kind=? AND evidence_uid=?
                                      AND revision_uid=?
                                      AND reason IN ('no_longer_visible','unknown')
                                    """,
                                    (
                                        domain,
                                        scope_id,
                                        kind,
                                        evidence_uid,
                                        revision_uid,
                                    ),
                                )
                        if reason is not None:
                            tombstones += self._tombstone(
                                domain=domain,
                                scope_id=scope_id,
                                evidence_kind=kind,
                                evidence_uid=evidence_uid,
                                revision_uid=revision_uid,
                                reason=reason,
                                now=now,
                            )

                    lease_expiry = _iso(
                        completed_dt + timedelta(seconds=max_staleness_seconds)
                    )
                    self.db.execute(
                        """
                        INSERT INTO visibility_leases(
                          domain,scope_id,source_instance,supported_type,
                          type_fingerprint,filter_fingerprint,
                          inventory_run_id,last_success_at,
                          max_staleness_seconds,expires_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(
                          domain,scope_id,source_instance,supported_type,
                          type_fingerprint,filter_fingerprint
                        ) DO UPDATE SET
                          inventory_run_id=excluded.inventory_run_id,
                          last_success_at=excluded.last_success_at,
                          max_staleness_seconds=excluded.max_staleness_seconds,
                          expires_at=excluded.expires_at
                        """,
                        (
                            domain,
                            scope_id,
                            source_instance,
                            supported_type,
                            type_fingerprint,
                            filter_fingerprint,
                            run_id,
                            capture_completed_at,
                            max_staleness_seconds,
                            lease_expiry,
                        ),
                    )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

        return InventoryOutcome(
            run_id=run_id,
            complete=status == "complete",
            authorized=authorized,
            page_count=page_count,
            seen_count=len(seen),
            tombstones_written=tombstones,
            lease_expires_at=lease_expiry,
        )

    def record_inventory_failure(
        self,
        *,
        domain: str,
        scope_id: str,
        source_instance: str,
        supported_type: str,
        type_fingerprint: str,
        filter_fingerprint: str,
        failure_reason: str,
        capture_started_at: str,
        capture_completed_at: str,
        max_staleness_seconds: int,
        authorized: bool = True,
    ) -> InventoryOutcome:
        return self.record_inventory(
            domain=domain,
            scope_id=scope_id,
            source_instance=source_instance,
            supported_type=supported_type,
            type_fingerprint=type_fingerprint,
            filter_fingerprint=filter_fingerprint,
            seen_source_ids=(),
            current_revisions={},
            explicit_status={},
            complete=False,
            authorized=authorized,
            page_count=0,
            capture_started_at=capture_started_at,
            capture_completed_at=capture_completed_at,
            max_staleness_seconds=max_staleness_seconds,
            failure_reason=failure_reason,
        )

    def assert_scope_current(
        self,
        scope: ResolvedScope,
        *,
        now: datetime | None = None,
    ) -> None:
        rows = self.db.execute(
            """
            SELECT source_instance,supported_type,type_fingerprint,
                   filter_fingerprint,last_success_at,expires_at
            FROM visibility_leases
            WHERE domain=? AND scope_id=?
            ORDER BY source_instance,supported_type,last_success_at DESC
            """,
            (scope.domain, scope.scope_id),
        ).fetchall()
        if not rows:
            raise VisibilityExpired("corpus-access-denied")
        latest: dict[tuple[str, str], Any] = {}
        for row in rows:
            key = (str(row["source_instance"]), str(row["supported_type"]))
            latest.setdefault(key, row)
        moment = (now or _now_dt()).astimezone(timezone.utc)
        if any(_parse_iso(str(row["expires_at"])) <= moment for row in latest.values()):
            raise VisibilityExpired("corpus-access-denied")

    def record_merge(
        self,
        *,
        domain: str,
        scope_id: str,
        source_object_uid: str,
        target_object_uid: str,
        source_instance: str,
        provenance: Mapping[str, Any],
    ) -> int:
        if source_object_uid == target_object_uid:
            raise InventoryReconciliationError("merge endpoints must differ")
        if not provenance:
            raise InventoryReconciliationError("merge provenance is required")
        for object_uid in (source_object_uid, target_object_uid):
            row = self.db.execute(
                "SELECT 1 FROM objects WHERE domain=? AND scope_id=? AND object_uid=?",
                (domain, scope_id, object_uid),
            ).fetchone()
            if row is None:
                raise InventoryReconciliationError("merge endpoint is not cataloged")
        now = _iso(_now_dt())
        tombstones = 0
        with self.store.writer_lock():
            try:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute(
                    """
                    INSERT INTO evidence_merge_mappings(
                      domain,scope_id,source_object_uid,target_object_uid,
                      source_instance,provenance_json,active,created_at
                    ) VALUES(?,?,?,?,?,?,1,?)
                    ON CONFLICT(
                      domain,scope_id,source_object_uid,target_object_uid,
                      source_instance
                    ) DO UPDATE SET
                      provenance_json=excluded.provenance_json,active=1
                    """,
                    (
                        domain,
                        scope_id,
                        source_object_uid,
                        target_object_uid,
                        source_instance,
                        canonical_json(dict(provenance)),
                        now,
                    ),
                )
                for row in self.db.execute(
                    """
                    SELECT revision_uid FROM object_revisions
                    WHERE domain=? AND scope_id=? AND object_uid=?
                    """,
                    (domain, scope_id, source_object_uid),
                ):
                    tombstones += self._tombstone(
                        domain=domain,
                        scope_id=scope_id,
                        evidence_kind="object",
                        evidence_uid=source_object_uid,
                        revision_uid=str(row["revision_uid"]),
                        reason="no_longer_visible",
                        now=now,
                    )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return tombstones


__all__ = [
    "InventoryOutcome",
    "InventoryReconciliationError",
    "LifecycleAuthority",
    "TOMBSTONE_REASONS",
    "VisibilityError",
    "VisibilityExpired",
]
