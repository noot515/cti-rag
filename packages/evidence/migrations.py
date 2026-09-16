"""Explicit, version-checked SQLite migrations for the advanced evidence catalog."""

from __future__ import annotations

import sqlite3

CURRENT_SCHEMA_VERSION = 1


class MigrationError(RuntimeError):
    pass


_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS raw_payloads (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, sha256 TEXT NOT NULL,
  byte_length INTEGER NOT NULL CHECK(byte_length >= 0), created_at TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, sha256)
);
CREATE TABLE IF NOT EXISTS raw_payload_sources (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, sha256 TEXT NOT NULL,
  source_instance TEXT NOT NULL, source_object_id TEXT NOT NULL,
  normalizer_version TEXT NOT NULL, source_snapshot_id TEXT NOT NULL,
  upstream_origin TEXT NOT NULL, source_uri TEXT,
  PRIMARY KEY(domain, scope_id, sha256, source_instance, source_object_id, source_snapshot_id, normalizer_version),
  FOREIGN KEY(domain, scope_id, sha256) REFERENCES raw_payloads(domain, scope_id, sha256) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS objects (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, object_uid TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, object_uid)
);
CREATE TABLE IF NOT EXISTS object_revisions (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, object_uid TEXT NOT NULL,
  revision_uid TEXT NOT NULL, payload_json TEXT NOT NULL,
  lifecycle_state TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, revision_uid),
  UNIQUE(domain, scope_id, object_uid, revision_uid),
  FOREIGN KEY(domain, scope_id, object_uid) REFERENCES objects(domain, scope_id, object_uid) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS object_revision_sources (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, revision_uid TEXT NOT NULL,
  raw_sha256 TEXT NOT NULL, source_instance TEXT NOT NULL, source_object_id TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, revision_uid, raw_sha256, source_instance, source_object_id),
  FOREIGN KEY(domain, scope_id, revision_uid) REFERENCES object_revisions(domain, scope_id, revision_uid) ON DELETE RESTRICT,
  FOREIGN KEY(domain, scope_id, raw_sha256) REFERENCES raw_payloads(domain, scope_id, sha256) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS relations (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, relation_uid TEXT NOT NULL,
  source_object_uid TEXT NOT NULL, target_object_uid TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, relation_uid),
  FOREIGN KEY(domain, scope_id, source_object_uid) REFERENCES objects(domain, scope_id, object_uid) ON DELETE RESTRICT,
  FOREIGN KEY(domain, scope_id, target_object_uid) REFERENCES objects(domain, scope_id, object_uid) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS relation_revisions (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, relation_uid TEXT NOT NULL,
  revision_uid TEXT NOT NULL, payload_json TEXT NOT NULL,
  assertion_kind TEXT NOT NULL, lifecycle_state TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, revision_uid),
  UNIQUE(domain, scope_id, relation_uid, revision_uid),
  FOREIGN KEY(domain, scope_id, relation_uid) REFERENCES relations(domain, scope_id, relation_uid) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS relation_revision_sources (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, revision_uid TEXT NOT NULL,
  raw_sha256 TEXT NOT NULL, source_instance TEXT NOT NULL, source_object_id TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, revision_uid, raw_sha256, source_instance, source_object_id),
  FOREIGN KEY(domain, scope_id, revision_uid) REFERENCES relation_revisions(domain, scope_id, revision_uid) ON DELETE RESTRICT,
  FOREIGN KEY(domain, scope_id, raw_sha256) REFERENCES raw_payloads(domain, scope_id, sha256) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS chunks (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, chunk_uid TEXT NOT NULL,
  object_uid TEXT NOT NULL, object_revision_uid TEXT NOT NULL,
  payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, chunk_uid),
  FOREIGN KEY(domain, scope_id, object_uid) REFERENCES objects(domain, scope_id, object_uid) ON DELETE RESTRICT,
  FOREIGN KEY(domain, scope_id, object_revision_uid) REFERENCES object_revisions(domain, scope_id, revision_uid) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS chunk_sources (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, chunk_uid TEXT NOT NULL,
  raw_sha256 TEXT NOT NULL, source_instance TEXT NOT NULL, source_object_id TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, chunk_uid, raw_sha256, source_instance, source_object_id),
  FOREIGN KEY(domain, scope_id, chunk_uid) REFERENCES chunks(domain, scope_id, chunk_uid) ON DELETE RESTRICT,
  FOREIGN KEY(domain, scope_id, raw_sha256) REFERENCES raw_payloads(domain, scope_id, sha256) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS external_ids (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, namespace TEXT NOT NULL,
  value TEXT NOT NULL, object_uid TEXT NOT NULL, object_revision_uid TEXT NOT NULL,
  taxonomy TEXT, version TEXT,
  PRIMARY KEY(domain, scope_id, namespace, value, object_revision_uid),
  FOREIGN KEY(domain, scope_id, object_uid) REFERENCES objects(domain, scope_id, object_uid) ON DELETE RESTRICT,
  FOREIGN KEY(domain, scope_id, object_revision_uid) REFERENCES object_revisions(domain, scope_id, revision_uid) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_external_ids_lookup ON external_ids(domain, scope_id, namespace, value);
CREATE TABLE IF NOT EXISTS snapshots (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)),
  created_at TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS snapshot_membership (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
  evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('object','relation','chunk')),
  evidence_uid TEXT NOT NULL, revision_uid TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, snapshot_id, evidence_kind, evidence_uid, revision_uid),
  FOREIGN KEY(domain, scope_id, snapshot_id) REFERENCES snapshots(domain, scope_id, snapshot_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS index_jobs (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, job_id TEXT NOT NULL,
  snapshot_id TEXT NOT NULL, backend TEXT NOT NULL, status TEXT NOT NULL,
  requested_at TEXT NOT NULL, completed_at TEXT, error_code TEXT,
  PRIMARY KEY(domain, scope_id, job_id),
  FOREIGN KEY(domain, scope_id, snapshot_id) REFERENCES snapshots(domain, scope_id, snapshot_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS backend_acks (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, job_id TEXT NOT NULL,
  backend TEXT NOT NULL, ack_token TEXT NOT NULL, acknowledged_at TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, job_id, backend),
  FOREIGN KEY(domain, scope_id, job_id) REFERENCES index_jobs(domain, scope_id, job_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS checkpoints (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, source_instance TEXT NOT NULL,
  cursor_json TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, source_instance)
);
CREATE TABLE IF NOT EXISTS tombstones (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, evidence_kind TEXT NOT NULL,
  evidence_uid TEXT NOT NULL, revision_uid TEXT NOT NULL, reason TEXT NOT NULL,
  tombstoned_at TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, evidence_kind, evidence_uid, revision_uid)
);
CREATE TABLE IF NOT EXISTS poll_observations (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, evidence_kind TEXT NOT NULL,
  revision_uid TEXT NOT NULL, raw_sha256 TEXT NOT NULL,
  source_instance TEXT NOT NULL, source_snapshot_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, evidence_kind, revision_uid, raw_sha256, source_instance, source_snapshot_id),
  FOREIGN KEY(domain, scope_id, raw_sha256) REFERENCES raw_payloads(domain, scope_id, sha256) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS evidence_equivalences (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, relation_revision_uid TEXT NOT NULL,
  source_object_uid TEXT NOT NULL, target_object_uid TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, relation_revision_uid),
  FOREIGN KEY(domain, scope_id, relation_revision_uid) REFERENCES relation_revisions(domain, scope_id, revision_uid) ON DELETE RESTRICT,
  FOREIGN KEY(domain, scope_id, source_object_uid) REFERENCES objects(domain, scope_id, object_uid) ON DELETE RESTRICT,
  FOREIGN KEY(domain, scope_id, target_object_uid) REFERENCES objects(domain, scope_id, object_uid) ON DELETE RESTRICT
);
"""


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current > CURRENT_SCHEMA_VERSION:
        raise MigrationError(
            f"catalog schema version {current} is newer than supported {CURRENT_SCHEMA_VERSION}"
        )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    if current == 0:
        script = (
            "BEGIN IMMEDIATE;\n"
            + _SCHEMA_V1
            + "\nINSERT OR IGNORE INTO schema_migrations(version, applied_at) "
            "VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ','now'));\n"
            "PRAGMA user_version=1;\nCOMMIT;"
        )
        try:
            connection.executescript(script)
        except Exception:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            raise
        current = 1
    rows = {int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}
    if current != CURRENT_SCHEMA_VERSION or CURRENT_SCHEMA_VERSION not in rows:
        raise MigrationError(
            "catalog migration history is inconsistent; destructive reset is forbidden"
        )
