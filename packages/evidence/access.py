"""Server-owned corpus grants for the advanced retrieval path."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal

from pydantic import Field, model_validator

from packages.evidence.policy import PolicyDecision, ResolvedScope, TrustedPrincipal
from packages.evidence.schema import AuthorizedEvidenceView, EvidenceModel


class CorpusAccessError(RuntimeError):
    pass


class CorpusAccessDenied(PermissionError, CorpusAccessError):
    pass


class CorpusAccessUnavailable(CorpusAccessError):
    pass


class CorpusRegistrationDenied(PermissionError, CorpusAccessError):
    pass


class CorpusGrant(EvidenceModel):
    principal_namespace: str = Field(min_length=1)
    principal_id: str = Field(min_length=1)


class CorpusRegistrationManifest(EvidenceModel):
    schema_version: Literal["corpus-grant-manifest-v1"] = "corpus-grant-manifest-v1"
    corpus_key: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    active_catalog_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    source_allowlist: frozenset[str]
    allowed_destinations: frozenset[str]
    enabled: bool = True
    grants: tuple[CorpusGrant, ...] = ()

    @model_validator(mode="after")
    def explicit_sources_and_unique_grants(self):
        if not self.source_allowlist:
            raise ValueError(
                "corpus registration requires an explicit source allowlist"
            )
        keys = [
            (grant.principal_namespace, grant.principal_id)
            for grant in self.grants
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("corpus registration contains duplicate grants")
        return self


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class CorpusAccessStore:
    """Explicit advanced authority store; legacy request ownership is never imported."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        try:
            self.connection = sqlite3.connect(
                self.path,
                isolation_level=None,
                check_same_thread=False,
                timeout=1.0,
            )
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self._migrate()
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except sqlite3.Error as exc:
            raise CorpusAccessUnavailable(
                "corpus access store unavailable"
            ) from exc

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS advanced_corpora (
              corpus_key TEXT PRIMARY KEY,
              domain TEXT NOT NULL,
              scope_id TEXT NOT NULL,
              active_catalog_id TEXT NOT NULL,
              policy_version TEXT NOT NULL,
              source_allowlist_json TEXT NOT NULL,
              allowed_destinations_json TEXT NOT NULL,
              enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS advanced_corpus_grants (
              corpus_key TEXT NOT NULL,
              principal_namespace TEXT NOT NULL,
              principal_id TEXT NOT NULL,
              revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)),
              granted_at TEXT NOT NULL,
              revoked_at TEXT,
              PRIMARY KEY(corpus_key, principal_namespace, principal_id),
              FOREIGN KEY(corpus_key) REFERENCES advanced_corpora(corpus_key)
                ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS advanced_grant_lookup
              ON advanced_corpus_grants(
                principal_namespace,principal_id,corpus_key,revoked
              );
            """
        )

    @staticmethod
    def _require_admin(actor: TrustedPrincipal) -> None:
        if (
            actor.source != "trusted_local_cli"
            or "corpus:register" not in actor.capabilities
        ):
            raise CorpusRegistrationDenied(
                "trusted local corpus administrator required"
            )

    def register_corpus(
        self,
        manifest: CorpusRegistrationManifest,
        *,
        actor: TrustedPrincipal,
    ) -> None:
        self._require_admin(actor)
        now = _now()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                """
                INSERT INTO advanced_corpora(
                  corpus_key,domain,scope_id,active_catalog_id,policy_version,
                  source_allowlist_json,allowed_destinations_json,enabled,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(corpus_key) DO UPDATE SET
                  domain=excluded.domain,
                  scope_id=excluded.scope_id,
                  active_catalog_id=excluded.active_catalog_id,
                  policy_version=excluded.policy_version,
                  source_allowlist_json=excluded.source_allowlist_json,
                  allowed_destinations_json=excluded.allowed_destinations_json,
                  enabled=excluded.enabled,
                  updated_at=excluded.updated_at
                """,
                (
                    manifest.corpus_key,
                    manifest.domain,
                    manifest.scope_id,
                    manifest.active_catalog_id,
                    manifest.policy_version,
                    json.dumps(
                        sorted(manifest.source_allowlist),
                        separators=(",", ":"),
                    ),
                    json.dumps(
                        sorted(manifest.allowed_destinations),
                        separators=(",", ":"),
                    ),
                    1 if manifest.enabled else 0,
                    now,
                ),
            )
            self.connection.execute(
                "UPDATE advanced_corpus_grants SET revoked=1,revoked_at=? "
                "WHERE corpus_key=?",
                (now, manifest.corpus_key),
            )
            for grant in sorted(
                manifest.grants,
                key=lambda item: (
                    item.principal_namespace,
                    item.principal_id,
                ),
            ):
                self.connection.execute(
                    """
                    INSERT INTO advanced_corpus_grants(
                      corpus_key,principal_namespace,principal_id,
                      revoked,granted_at,revoked_at
                    ) VALUES (?,?,?,?,?,NULL)
                    ON CONFLICT(
                      corpus_key,principal_namespace,principal_id
                    ) DO UPDATE SET
                      revoked=0,
                      granted_at=excluded.granted_at,
                      revoked_at=NULL
                    """,
                    (
                        manifest.corpus_key,
                        grant.principal_namespace,
                        grant.principal_id,
                        0,
                        now,
                    ),
                )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise CorpusAccessUnavailable(
                "corpus access store unavailable"
            ) from exc
        except Exception:
            self.connection.rollback()
            raise

    def revoke_grant(
        self,
        *,
        corpus_key: str,
        principal_namespace: str,
        principal_id: str,
        actor: TrustedPrincipal,
    ) -> None:
        self._require_admin(actor)
        try:
            self.connection.execute(
                "UPDATE advanced_corpus_grants SET revoked=1,revoked_at=? "
                "WHERE corpus_key=? AND principal_namespace=? AND principal_id=?",
                (
                    _now(),
                    corpus_key,
                    principal_namespace,
                    principal_id,
                ),
            )
        except sqlite3.Error as exc:
            raise CorpusAccessUnavailable(
                "corpus access store unavailable"
            ) from exc

    def _corpus_row(self, corpus_key: str) -> sqlite3.Row | None:
        try:
            return self.connection.execute(
                "SELECT * FROM advanced_corpora WHERE corpus_key=?",
                (corpus_key,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise CorpusAccessUnavailable(
                "corpus access store unavailable"
            ) from exc

    def resolve_scope(
        self,
        principal: TrustedPrincipal,
        corpus_key: str,
    ) -> ResolvedScope:
        row = self._corpus_row(corpus_key)
        if row is None or not bool(row["enabled"]):
            raise CorpusAccessDenied("corpus-access-denied")
        try:
            active_count = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM advanced_corpus_grants "
                    "WHERE corpus_key=? AND revoked=0",
                    (corpus_key,),
                ).fetchone()[0]
            )
            grant = self.connection.execute(
                "SELECT 1 FROM advanced_corpus_grants WHERE corpus_key=? "
                "AND principal_namespace=? AND principal_id=? AND revoked=0",
                (
                    corpus_key,
                    principal.principal_namespace,
                    principal.principal_id,
                ),
            ).fetchone()
        except sqlite3.Error as exc:
            raise CorpusAccessUnavailable(
                "corpus access store unavailable"
            ) from exc
        # Unknown, ownerless and unauthorized all use the same external denial.
        if active_count == 0 or grant is None:
            raise CorpusAccessDenied("corpus-access-denied")
        return ResolvedScope(
            principal_id=principal.principal_id,
            principal_namespace=principal.principal_namespace,
            corpus_id=corpus_key,
            domain=str(row["domain"]),
            scope_id=str(row["scope_id"]),
            active_catalog_id=str(row["active_catalog_id"]),
            policy_version=str(row["policy_version"]),
            source_allowlist=frozenset(
                json.loads(row["source_allowlist_json"])
            ),
            allowed_destinations=frozenset(
                json.loads(row["allowed_destinations_json"])
            ),
        )

    def assert_scope_current(
        self,
        principal: TrustedPrincipal,
        scope: ResolvedScope,
    ) -> None:
        current = self.resolve_scope(principal, scope.corpus_id)
        if (
            current.domain,
            current.scope_id,
            current.active_catalog_id,
            current.policy_version,
            current.source_allowlist,
            current.allowed_destinations,
        ) != (
            scope.domain,
            scope.scope_id,
            scope.active_catalog_id,
            scope.policy_version,
            scope.source_allowlist,
            scope.allowed_destinations,
        ):
            raise CorpusAccessDenied("corpus-access-denied")


class CorpusGrantPolicy:
    """Grant-aware fail-closed evidence policy for advanced requests."""

    def __init__(
        self,
        store: CorpusAccessStore,
        principal: TrustedPrincipal,
        freshness_authority: object | None = None,
    ) -> None:
        self.store = store
        self.principal = principal
        self.freshness_authority = freshness_authority
        self.policy_version = "server-corpus-grants-v2"

    def assert_scope_current(self, scope: ResolvedScope) -> None:
        self.store.assert_scope_current(self.principal, scope)
        if self.freshness_authority is not None:
            try:
                self.freshness_authority.assert_scope_current(scope)
            except PermissionError as exc:
                raise CorpusAccessDenied("corpus-access-denied") from exc

    def resolve_scope(
        self,
        principal: TrustedPrincipal,
        corpus: str,
    ) -> ResolvedScope:
        if (
            principal.principal_id,
            principal.principal_namespace,
            principal.source,
        ) != (
            self.principal.principal_id,
            self.principal.principal_namespace,
            self.principal.source,
        ):
            raise CorpusAccessDenied("corpus-access-denied")
        scope = self.store.resolve_scope(principal, corpus)
        self.assert_scope_current(scope)
        return scope

    def authorize_evidence(
        self,
        view: AuthorizedEvidenceView,
        scope: ResolvedScope,
        destination: str,
    ) -> PolicyDecision:
        try:
            self.assert_scope_current(scope)
        except CorpusAccessDenied:
            return PolicyDecision(
                allowed=False,
                reason="corpus-access-denied",
            )
        if destination not in scope.allowed_destinations:
            return PolicyDecision(
                allowed=False,
                reason="destination-not-permitted",
            )
        if view.domain != scope.domain or view.scope_id != scope.scope_id:
            return PolicyDecision(
                allowed=False,
                reason="domain-or-scope-mismatch",
            )
        if (
            not view.source_instances
            or not set(view.source_instances).issubset(scope.source_allowlist)
        ):
            return PolicyDecision(
                allowed=False,
                reason="source-not-authorized",
            )
        if view.policy.unresolved_markings or view.policy.granular_selectors:
            return PolicyDecision(
                allowed=False,
                reason="unresolved-or-granular-marking",
            )
        dissemination = set(view.policy.dissemination)
        if dissemination and dissemination != {"tlp:clear"}:
            return PolicyDecision(
                allowed=False,
                reason="restricted-marking-policy-not-configured",
            )
        return PolicyDecision(
            allowed=True,
            reason="server-corpus-grant",
        )


__all__ = [
    "CorpusAccessDenied",
    "CorpusAccessError",
    "CorpusAccessStore",
    "CorpusAccessUnavailable",
    "CorpusGrant",
    "CorpusGrantPolicy",
    "CorpusRegistrationDenied",
    "CorpusRegistrationManifest",
]
