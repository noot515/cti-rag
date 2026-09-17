"""Persistent, snapshot-pinned exact identifier retrieval for the advanced path."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from packages.evidence.ids import canonical_json
from packages.evidence.policy import ResolvedScope
from packages.evidence.schema import ExternalIdentifier, SnapshotRef
from packages.indexing.manifests import GenerationManifest
from .candidate import BackendHit


class ExactIndexError(RuntimeError):
    pass


def _safe_component(value: str) -> str:
    if value and all(ch.isalnum() or ch in "._-" for ch in value):
        return value
    return sha256(value.encode("utf-8")).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json(payload).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return sha256(encoded).hexdigest()


def _catalog_entries(store: Any, *, domain: str, scope_id: str, generation_id: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    member_rows = store.connection.execute(
        "SELECT evidence_uid,revision_uid FROM snapshot_membership "
        "WHERE domain=? AND scope_id=? AND snapshot_id=? AND evidence_kind='object' "
        "ORDER BY revision_uid,evidence_uid",
        (domain, scope_id, generation_id),
    ).fetchall()
    object_membership = [
        {"object_uid": row["evidence_uid"], "object_revision_uid": row["revision_uid"]}
        for row in member_rows
    ]
    entries: list[dict[str, str]] = []
    for member in object_membership:
        object_uid = member["object_uid"]
        revision_uid = member["object_revision_uid"]
        for identifier in store.connection.execute(
            "SELECT namespace,value FROM external_ids WHERE domain=? AND scope_id=? AND object_uid=? AND object_revision_uid=? "
            "ORDER BY namespace,value",
            (domain, scope_id, object_uid, revision_uid),
        ):
            entries.append({"key": f"{identifier['namespace']}:{identifier['value']}", "object_uid": object_uid, "object_revision_uid": revision_uid, "match_kind": "external_identifier"})
        for source in store.connection.execute(
            "SELECT source_instance,source_object_id FROM object_revision_sources "
            "WHERE domain=? AND scope_id=? AND revision_uid=? ORDER BY source_instance,source_object_id",
            (domain, scope_id, revision_uid),
        ):
            entries.append({"key": f"source:{source['source_instance']}:{source['source_object_id']}", "object_uid": object_uid, "object_revision_uid": revision_uid, "match_kind": "source_identifier"})
        revision = store.connection.execute(
            "SELECT payload_json FROM object_revisions WHERE domain=? AND scope_id=? AND revision_uid=?",
            (domain, scope_id, revision_uid),
        ).fetchone()
        if revision is None:
            raise ExactIndexError("object revision disappeared while validating exact index")
        stix_id = json.loads(revision["payload_json"]).get("stix_id")
        if stix_id:
            entries.append({"key": f"stix:{stix_id}", "object_uid": object_uid, "object_revision_uid": revision_uid, "match_kind": "stix_identifier"})
    unique = {(item["key"], item["object_uid"], item["object_revision_uid"], item["match_kind"]): item for item in entries}
    return object_membership, [unique[key] for key in sorted(unique)]


class ExactIndex:
    """Validated JSON exact index built from catalog identity mappings only."""

    schema_version = "exact-index-v1"
    name = "exact"

    def __init__(self, store: Any, path: Path, payload: dict[str, Any]) -> None:
        self.store = store
        self.path = path
        self.payload = payload
        self.domain = str(payload["domain"])
        self.scope_id = str(payload["scope_id"])
        self.corpus_id = str(payload["corpus_id"])
        self.generation_id = str(payload["generation_id"])
        self.manifest_sha256 = str(payload["manifest_sha256"])
        self.membership_sha256 = str(payload["membership_sha256"])
        self.entries = tuple(payload["entries"])
        mapping: dict[str, list[dict[str, Any]]] = {}
        for entry in self.entries:
            mapping.setdefault(str(entry["key"]), []).append(entry)
        self._by_key = {
            key: tuple(sorted(values, key=lambda item: (item["object_revision_uid"], item["object_uid"], item["match_kind"])))
            for key, values in mapping.items()
        }

    @classmethod
    def path_for(cls, root: Path | str, *, domain: str, scope_id: str, generation_id: str) -> Path:
        return Path(root) / _safe_component(domain) / _safe_component(scope_id) / _safe_component(generation_id) / "exact.json"

    @classmethod
    def build(cls, store: Any, *, root: Path | str, manifest: GenerationManifest) -> "ExactIndex":
        row = store.connection.execute(
            "SELECT manifest_sha256 FROM generation_manifests WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?",
            (manifest.domain, manifest.scope_id, manifest.corpus_id, manifest.generation_id),
        ).fetchone()
        if row is None or row["manifest_sha256"] != manifest.manifest_sha256:
            raise ExactIndexError("generation manifest is missing or mismatched")
        object_membership, entries = _catalog_entries(
            store, domain=manifest.domain, scope_id=manifest.scope_id, generation_id=manifest.generation_id
        )
        payload = {
            "schema_version": cls.schema_version,
            "domain": manifest.domain,
            "scope_id": manifest.scope_id,
            "corpus_id": manifest.corpus_id,
            "generation_id": manifest.generation_id,
            "manifest_sha256": manifest.manifest_sha256,
            "membership_sha256": manifest.membership_sha256,
            "object_membership": object_membership,
            "entries": entries,
        }
        path = cls.path_for(root, domain=manifest.domain, scope_id=manifest.scope_id, generation_id=manifest.generation_id)
        _atomic_json(path, payload)
        return cls.open(store, path=path)

    @classmethod
    def open(cls, store: Any, *, path: Path | str) -> "ExactIndex":
        path = Path(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExactIndexError("exact index cannot be read") from exc
        if payload.get("schema_version") != cls.schema_version:
            raise ExactIndexError("unsupported exact index schema")
        generation = store.connection.execute(
            "SELECT manifest_sha256,manifest_json FROM generation_manifests "
            "WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?",
            (payload.get("domain"), payload.get("scope_id"), payload.get("corpus_id"), payload.get("generation_id")),
        ).fetchone()
        if generation is None or generation["manifest_sha256"] != payload.get("manifest_sha256"):
            raise ExactIndexError("generation manifest does not match exact index")
        manifest = GenerationManifest.model_validate_json(generation["manifest_json"])
        if manifest.membership_sha256 != payload.get("membership_sha256"):
            raise ExactIndexError("generation membership hash does not match exact index")
        observed_membership, expected_entries = _catalog_entries(
            store, domain=payload["domain"], scope_id=payload["scope_id"], generation_id=payload["generation_id"]
        )
        if observed_membership != payload.get("object_membership"):
            raise ExactIndexError("exact index object membership is stale or corrupt")
        if expected_entries != payload.get("entries"):
            raise ExactIndexError("exact index identity mappings are stale or corrupt")
        return cls(store, path, payload)

    @property
    def artifact_sha256(self) -> str:
        return sha256(self.path.read_bytes()).hexdigest()

    def _validate_request(self, scope: ResolvedScope, snapshot: SnapshotRef) -> None:
        if (scope.domain, scope.scope_id, scope.corpus_id) != (self.domain, self.scope_id, self.corpus_id):
            raise ExactIndexError("resolved scope does not match exact index")
        if (snapshot.domain, snapshot.scope_id) != (self.domain, self.scope_id):
            raise ExactIndexError("snapshot scope does not match exact index")
        if snapshot.snapshot_id != self.generation_id or snapshot.manifest_sha256 != self.manifest_sha256:
            raise ExactIndexError("snapshot does not match exact generation")

    def _live_allowed(self, object_uid: str, revision_uid: str) -> bool:
        tombstone = self.store.connection.execute(
            "SELECT 1 FROM tombstones WHERE domain=? AND scope_id=? AND (evidence_uid=? OR revision_uid=?) LIMIT 1",
            (self.domain, self.scope_id, object_uid, revision_uid),
        ).fetchone()
        if tombstone is not None:
            return False
        withdrawn = self.store.connection.execute(
            "SELECT 1 FROM object_revisions WHERE domain=? AND scope_id=? AND object_uid=? "
            "AND lifecycle_state IN ('revoked','deleted') LIMIT 1",
            (self.domain, self.scope_id, object_uid),
        ).fetchone()
        return withdrawn is None

    def lookup(self, identifier: ExternalIdentifier | str, *, scope: ResolvedScope, snapshot: SnapshotRef, top_k: int = 20) -> tuple[BackendHit, ...]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self._validate_request(scope, snapshot)
        if isinstance(identifier, ExternalIdentifier):
            if identifier.domain not in {None, self.domain}:
                return ()
            key = f"{identifier.namespace}:{identifier.value}"
        elif isinstance(identifier, str) and (identifier.startswith("source:") or identifier.startswith("stix:")):
            key = identifier
        else:
            raise ValueError("string exact keys must use source: or stix: prefixes")
        entries = [item for item in self._by_key.get(key, ()) if self._live_allowed(item["object_uid"], item["object_revision_uid"])][:top_k]
        return tuple(
            BackendHit(
                backend_key=f"exact:{self.generation_id}:{rank}",
                domain=self.domain,
                scope_id=self.scope_id,
                snapshot_id=self.generation_id,
                logical_uid=item["object_revision_uid"],
                raw_score=1.0,
                metadata={"rank": rank, "object_uid": item["object_uid"], "object_revision_uid": item["object_revision_uid"], "match_kind": item["match_kind"], "exact_key": key},
            )
            for rank, item in enumerate(entries, start=1)
        )


__all__ = ["ExactIndex", "ExactIndexError"]
