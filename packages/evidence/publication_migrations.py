"""Versioned, opt-in schema migration for generation publication mechanics."""
from __future__ import annotations

import sqlite3

PUBLICATION_SCHEMA_VERSION = 1


class PublicationMigrationError(RuntimeError):
    pass


_SCHEMA = """
CREATE TABLE IF NOT EXISTS publication_schema_migrations (
  version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS generation_manifests (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, corpus_id TEXT NOT NULL, generation_id TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL, manifest_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('building','ready','active','failed')),
  created_at TEXT NOT NULL, ready_at TEXT, activated_at TEXT, failed_reason TEXT,
  PRIMARY KEY(domain, scope_id, corpus_id, generation_id),
  UNIQUE(domain, scope_id, corpus_id, manifest_sha256),
  FOREIGN KEY(domain, scope_id, generation_id) REFERENCES snapshots(domain, scope_id, snapshot_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS publication_jobs (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, corpus_id TEXT NOT NULL, generation_id TEXT NOT NULL,
  job_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('building','activated','completed','failed')),
  requested_at TEXT NOT NULL, completed_at TEXT, error_code TEXT,
  PRIMARY KEY(domain, scope_id, corpus_id, job_id),
  FOREIGN KEY(domain, scope_id, corpus_id, generation_id) REFERENCES generation_manifests(domain, scope_id, corpus_id, generation_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS projection_jobs (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, corpus_id TEXT NOT NULL, generation_id TEXT NOT NULL,
  backend TEXT NOT NULL, required INTEGER NOT NULL CHECK(required IN (0,1)),
  status TEXT NOT NULL CHECK(status IN ('pending','verified','failed')),
  manifest_sha256 TEXT NOT NULL, requested_at TEXT NOT NULL, completed_at TEXT, error_code TEXT,
  PRIMARY KEY(domain, scope_id, corpus_id, generation_id, backend),
  FOREIGN KEY(domain, scope_id, corpus_id, generation_id) REFERENCES generation_manifests(domain, scope_id, corpus_id, generation_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS projection_receipts (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, corpus_id TEXT NOT NULL, generation_id TEXT NOT NULL,
  backend TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, membership_sha256 TEXT NOT NULL,
  member_count INTEGER NOT NULL CHECK(member_count >= 0), fingerprint TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL, visibility_verified INTEGER NOT NULL CHECK(visibility_verified IN (0,1)),
  sentinel TEXT NOT NULL, receipt_json TEXT NOT NULL, verified_at TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, corpus_id, generation_id, backend),
  FOREIGN KEY(domain, scope_id, corpus_id, generation_id, backend) REFERENCES projection_jobs(domain, scope_id, corpus_id, generation_id, backend) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS active_generations (
  domain TEXT NOT NULL, scope_id TEXT NOT NULL, corpus_id TEXT NOT NULL,
  generation_id TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(domain, scope_id, corpus_id),
  FOREIGN KEY(domain, scope_id, corpus_id, generation_id) REFERENCES generation_manifests(domain, scope_id, corpus_id, generation_id) ON DELETE RESTRICT
);
"""


def apply_publication_migrations(connection: sqlite3.Connection) -> None:
    current_row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='publication_schema_migrations'"
    ).fetchone()
    current = 0
    if current_row:
        row = connection.execute("SELECT MAX(version) FROM publication_schema_migrations").fetchone()
        current = int(row[0] or 0)
    if current > PUBLICATION_SCHEMA_VERSION:
        raise PublicationMigrationError(
            f"publication schema version {current} is newer than supported {PUBLICATION_SCHEMA_VERSION}"
        )
    if current == 0:
        script = (
            "BEGIN IMMEDIATE;\n" + _SCHEMA +
            "\nINSERT OR IGNORE INTO publication_schema_migrations(version, applied_at) "
            "VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ','now'));\nCOMMIT;"
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
    rows = {int(row[0]) for row in connection.execute("SELECT version FROM publication_schema_migrations")}
    if current != PUBLICATION_SCHEMA_VERSION or PUBLICATION_SCHEMA_VERSION not in rows:
        raise PublicationMigrationError("publication migration history is inconsistent; destructive reset is forbidden")
