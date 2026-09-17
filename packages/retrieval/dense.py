"""Generation-scoped deterministic dense fixture projection and channel."""
from __future__ import annotations

from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from packages.evidence.ids import canonical_hash, canonical_json
from packages.evidence.policy import ResolvedScope, require_authorized
from packages.evidence.schema import (
    AuthorizedEvidenceView,
    ChannelScore,
    ChunkCandidate,
    EvidencePolicyMetadata,
    SnapshotRef,
)
from packages.indexing.manifests import GenerationManifest, ProjectionReceipt
from .candidate import BackendHit, ChannelResult
from .providers import (
    EgressDestination,
    EmbeddingDeadlineExceeded,
    EmbeddingFingerprintMismatch,
    EmbeddingInput,
    EmbeddingProvider,
    EmbeddingValidationError,
    validate_embedding_batch,
)


class DenseIndexError(RuntimeError):
    pass


class DenseFingerprintMismatch(DenseIndexError, EmbeddingFingerprintMismatch):
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


def _chunk_rows(store: Any, manifest: GenerationManifest) -> list[dict[str, Any]]:
    rows = store.connection.execute(
        "SELECT sm.evidence_uid AS chunk_uid,c.object_uid,c.object_revision_uid,c.payload_json "
        "FROM snapshot_membership sm JOIN chunks c "
        "ON c.domain=sm.domain AND c.scope_id=sm.scope_id AND c.chunk_uid=sm.evidence_uid "
        "WHERE sm.domain=? AND sm.scope_id=? AND sm.snapshot_id=? AND sm.evidence_kind='chunk' "
        "ORDER BY sm.evidence_uid",
        (manifest.domain, manifest.scope_id, manifest.generation_id),
    ).fetchall()
    return [
        {
            "chunk_uid": row["chunk_uid"],
            "object_uid": row["object_uid"],
            "object_revision_uid": row["object_revision_uid"],
            "payload": json.loads(row["payload_json"]),
        }
        for row in rows
    ]


def _view(row: dict[str, Any], *, domain: str, scope_id: str) -> AuthorizedEvidenceView:
    policy_payload = row["payload"].get("policy") or {}
    return AuthorizedEvidenceView(
        evidence_uid=row["chunk_uid"],
        domain=domain,
        scope_id=scope_id,
        source_instances=tuple(policy_payload.get("source_instances", ())),
        policy=EvidencePolicyMetadata.model_validate(policy_payload),
    )


def _score(query: tuple[float, ...], document: tuple[float, ...], metric: str) -> float:
    if metric in {"cosine", "ip"}:
        if metric == "cosine":
            qnorm = math.sqrt(sum(value * value for value in query))
            dnorm = math.sqrt(sum(value * value for value in document))
            if qnorm == 0.0 or dnorm == 0.0:
                return 0.0
            return sum(a * b for a, b in zip(query, document)) / (qnorm * dnorm)
        return sum(a * b for a, b in zip(query, document))
    if metric == "l2":
        return -sum((a - b) ** 2 for a, b in zip(query, document))
    raise DenseIndexError(f"unsupported dense metric: {metric}")


class DenseIndex:
    schema_version = "fixture-dense-index-v1"
    name = "dense"

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
        self.embedding_fingerprint = payload["embedding_fingerprint"]
        self.embedding_fingerprint_digest = str(payload["embedding_fingerprint_digest"])
        self.entries = tuple(payload["entries"])

    @classmethod
    def path_for(cls, root: Path | str, *, domain: str, scope_id: str, generation_id: str) -> Path:
        return (
            Path(root)
            / _safe_component(domain)
            / _safe_component(scope_id)
            / _safe_component(generation_id)
            / "dense.json"
        )

    @classmethod
    def build(
        cls,
        store: Any,
        *,
        root: Path | str,
        manifest: GenerationManifest,
        provider: EmbeddingProvider,
        scope: ResolvedScope,
        policy: Any,
        destination: EgressDestination,
        deadline: float | None = None,
    ) -> "DenseIndex":
        if (scope.domain, scope.scope_id, scope.corpus_id) != (
            manifest.domain,
            manifest.scope_id,
            manifest.corpus_id,
        ):
            raise DenseIndexError("resolved scope does not match generation manifest")
        spec = next((item for item in manifest.enabled_projections if item.backend == "dense"), None)
        if spec is None:
            raise DenseIndexError("generation does not enable dense projection")
        if spec.fingerprint != provider.fingerprint.digest:
            raise DenseFingerprintMismatch("dense provider fingerprint differs from generation; reindex required")

        rows = _chunk_rows(store, manifest)
        inputs: list[EmbeddingInput] = []
        metadata: dict[str, dict[str, Any]] = {}
        for row in rows:
            require_authorized(policy.authorize_evidence(_view(row, domain=manifest.domain, scope_id=manifest.scope_id), scope, destination))
            inputs.append(EmbeddingInput(item_id=row["chunk_uid"], text=str(row["payload"].get("text", ""))))
            metadata[row["chunk_uid"]] = {
                "object_uid": row["object_uid"],
                "object_revision_uid": row["object_revision_uid"],
            }

        batch = provider.encode_documents(
            inputs,
            destination=destination,
            deadline=deadline,
        )
        batch = validate_embedding_batch(
            batch,
            expected_ids=(item.item_id for item in inputs),
            expected_fingerprint=provider.fingerprint,
        )
        entries = [
            {
                "chunk_uid": item.item_id,
                "object_uid": metadata[item.item_id]["object_uid"],
                "object_revision_uid": metadata[item.item_id]["object_revision_uid"],
                "vector": list(item.vector),
            }
            for item in batch.embeddings
        ]
        payload = {
            "schema_version": cls.schema_version,
            "domain": manifest.domain,
            "scope_id": manifest.scope_id,
            "corpus_id": manifest.corpus_id,
            "generation_id": manifest.generation_id,
            "manifest_sha256": manifest.manifest_sha256,
            "membership_sha256": manifest.membership_sha256,
            "embedding_fingerprint": provider.fingerprint.model_dump(mode="json"),
            "embedding_fingerprint_digest": provider.fingerprint.digest,
            "entries": entries,
        }
        path = cls.path_for(root, domain=manifest.domain, scope_id=manifest.scope_id, generation_id=manifest.generation_id)
        _atomic_json(path, payload)
        return cls.open(store, path=path, provider=provider)

    @classmethod
    def open(
        cls,
        store: Any,
        *,
        path: Path | str,
        provider: EmbeddingProvider,
    ) -> "DenseIndex":
        path = Path(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DenseIndexError("dense index cannot be read") from exc
        if payload.get("schema_version") != cls.schema_version:
            raise DenseIndexError("unsupported dense index schema")
        if payload.get("embedding_fingerprint_digest") != provider.fingerprint.digest:
            raise DenseFingerprintMismatch("dense provider fingerprint differs from index; reindex required")
        generation = store.connection.execute(
            "SELECT manifest_sha256,manifest_json FROM generation_manifests "
            "WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?",
            (
                payload.get("domain"),
                payload.get("scope_id"),
                payload.get("corpus_id"),
                payload.get("generation_id"),
            ),
        ).fetchone()
        if generation is None or generation["manifest_sha256"] != payload.get("manifest_sha256"):
            raise DenseIndexError("generation manifest does not match dense index")
        manifest = GenerationManifest.model_validate_json(generation["manifest_json"])
        if manifest.membership_sha256 != payload.get("membership_sha256"):
            raise DenseIndexError("generation membership hash does not match dense index")
        expected = {row["chunk_uid"] for row in _chunk_rows(store, manifest)}
        observed = {str(item.get("chunk_uid")) for item in payload.get("entries", [])}
        if expected != observed or len(observed) != len(payload.get("entries", [])):
            raise DenseIndexError("dense index chunk membership is stale or corrupt")
        validate_embedding_batch(
            provider_batch(provider, payload.get("entries", [])),
            expected_ids=sorted(expected),
            expected_fingerprint=provider.fingerprint,
        )
        return cls(store, path, payload)

    @property
    def artifact_sha256(self) -> str:
        return sha256(self.path.read_bytes()).hexdigest()

    def _validate_request(self, scope: ResolvedScope, snapshot: SnapshotRef) -> None:
        if (scope.domain, scope.scope_id, scope.corpus_id) != (self.domain, self.scope_id, self.corpus_id):
            raise DenseIndexError("resolved scope does not match dense index")
        if (snapshot.domain, snapshot.scope_id) != (self.domain, self.scope_id):
            raise DenseIndexError("snapshot scope does not match dense index")
        if snapshot.snapshot_id != self.generation_id or snapshot.manifest_sha256 != self.manifest_sha256:
            raise DenseIndexError("snapshot does not match dense generation")

    def search(
        self,
        query: str,
        *,
        provider: EmbeddingProvider,
        scope: ResolvedScope,
        snapshot: SnapshotRef,
        destination: EgressDestination,
        top_k: int = 20,
        deadline: float | None = None,
    ) -> tuple[BackendHit, ...]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self._validate_request(scope, snapshot)
        if provider.fingerprint.digest != self.embedding_fingerprint_digest:
            raise DenseFingerprintMismatch("query provider fingerprint differs from index; reindex required")
        batch = provider.encode_queries(
            (EmbeddingInput(item_id="query", text=query),),
            destination=destination,
            deadline=deadline,
        )
        batch = validate_embedding_batch(
            batch,
            expected_ids=("query",),
            expected_fingerprint=provider.fingerprint,
        )
        qvec = batch.embeddings[0].vector
        ranked: list[tuple[float, dict[str, Any]]] = []
        for entry in self.entries:
            if self._live_allowed(entry):
                ranked.append((_score(qvec, tuple(entry["vector"]), provider.fingerprint.metric), entry))
        ranked.sort(key=lambda item: (-item[0], item[1]["chunk_uid"]))
        return tuple(
            BackendHit(
                backend_key=f"dense:{self.generation_id}:{entry['chunk_uid']}",
                domain=self.domain,
                scope_id=self.scope_id,
                snapshot_id=self.generation_id,
                logical_uid=entry["chunk_uid"],
                raw_score=score,
                metadata={
                    "rank": rank,
                    "object_uid": entry["object_uid"],
                    "object_revision_uid": entry["object_revision_uid"],
                    "score_kind": provider.fingerprint.metric,
                    "embedding_fingerprint": self.embedding_fingerprint_digest,
                },
            )
            for rank, (score, entry) in enumerate(ranked[:top_k], start=1)
        )

    def _live_allowed(self, entry: dict[str, Any]) -> bool:
        tombstone = self.store.connection.execute(
            "SELECT 1 FROM tombstones WHERE domain=? AND scope_id=? AND (evidence_uid=? OR evidence_uid=?) LIMIT 1",
            (self.domain, self.scope_id, entry["chunk_uid"], entry["object_uid"]),
        ).fetchone()
        if tombstone is not None:
            return False
        withdrawn = self.store.connection.execute(
            "SELECT 1 FROM object_revisions WHERE domain=? AND scope_id=? AND object_uid=? "
            "AND lifecycle_state IN ('revoked','deleted') LIMIT 1",
            (self.domain, self.scope_id, entry["object_uid"]),
        ).fetchone()
        return withdrawn is None

    def candidate_for_hit(
        self,
        hit: BackendHit,
        *,
        scope: ResolvedScope,
        snapshot: SnapshotRef,
        policy: Any,
    ) -> ChunkCandidate:
        self._validate_request(scope, snapshot)
        entry = next((item for item in self.entries if item["chunk_uid"] == hit.logical_uid), None)
        if entry is None:
            raise DenseIndexError("dense hit is not part of this generation")
        member = self.store.connection.execute(
            "SELECT 1 FROM snapshot_membership WHERE domain=? AND scope_id=? AND snapshot_id=? "
            "AND evidence_kind='chunk' AND evidence_uid=?",
            (self.domain, self.scope_id, self.generation_id, hit.logical_uid),
        ).fetchone()
        if member is None or not self._live_allowed(entry):
            raise PermissionError("dense chunk is not live in the pinned generation")
        row = self.store.connection.execute(
            "SELECT payload_json FROM chunks WHERE domain=? AND scope_id=? AND chunk_uid=?",
            (self.domain, self.scope_id, hit.logical_uid),
        ).fetchone()
        if row is None:
            raise DenseIndexError("dense chunk disappeared from catalog")
        payload = json.loads(row["payload_json"])
        view = _view(
            {"chunk_uid": hit.logical_uid, "payload": payload},
            domain=self.domain,
            scope_id=self.scope_id,
        )
        require_authorized(policy.authorize_evidence(view, scope, "caller"))
        return ChunkCandidate(
            candidate_id=canonical_hash(["candidate-v1", "dense", self.generation_id, hit.logical_uid]),
            domain=self.domain,
            scope_id=self.scope_id,
            snapshot=snapshot,
            target_object_uid=entry["object_uid"],
            authorized_view=view,
            provenance=(),
            channel_scores=(
                ChannelScore(
                    channel="dense",
                    rank=int(hit.metadata.get("rank", 1)),
                    raw_score=hit.raw_score,
                    score_kind=str(hit.metadata.get("score_kind", "dense")),
                ),
            ),
            chunk_uid=hit.logical_uid,
            object_uid=entry["object_uid"],
        )


def provider_batch(provider: EmbeddingProvider, entries: list[dict[str, Any]]):
    from .providers import EmbeddingBatch, IndexedEmbedding

    return EmbeddingBatch(
        fingerprint=provider.fingerprint,
        embeddings=tuple(
            IndexedEmbedding(item_id=str(item["chunk_uid"]), vector=tuple(item["vector"]))
            for item in sorted(entries, key=lambda item: str(item["chunk_uid"]))
        ),
    )


class DenseProjectionWriter:
    backend = "dense"

    def __init__(
        self,
        store: Any,
        root: Path | str,
        *,
        provider: EmbeddingProvider,
        scope: ResolvedScope,
        policy: Any,
        destination: EgressDestination = "local_generator",
        deadline_seconds: float = 30.0,
    ) -> None:
        self.store = store
        self.root = Path(root)
        self.provider = provider
        self.scope = scope
        self.policy = policy
        self.destination = destination
        self.deadline_seconds = deadline_seconds
        self.fingerprint = provider.fingerprint.digest

    def build(self, manifest: GenerationManifest) -> ProjectionReceipt:
        deadline = time.monotonic() + self.deadline_seconds
        index = DenseIndex.build(
            self.store,
            root=self.root,
            manifest=manifest,
            provider=self.provider,
            scope=self.scope,
            policy=self.policy,
            destination=self.destination,
            deadline=deadline,
        )
        return ProjectionReceipt(
            generation_id=manifest.generation_id,
            domain=manifest.domain,
            scope_id=manifest.scope_id,
            corpus_id=manifest.corpus_id,
            backend="dense",
            manifest_sha256=manifest.manifest_sha256,
            membership_sha256=manifest.membership_sha256,
            member_count=len(manifest.membership),
            fingerprint=self.fingerprint,
            artifact_sha256=index.artifact_sha256,
            visibility_verified=True,
            sentinel=f"dense:{len(index.entries)}:{index.artifact_sha256[:16]}",
        )

    def verify(self, manifest: GenerationManifest, receipt: ProjectionReceipt) -> bool:
        try:
            path = DenseIndex.path_for(
                self.root,
                domain=manifest.domain,
                scope_id=manifest.scope_id,
                generation_id=manifest.generation_id,
            )
            index = DenseIndex.open(self.store, path=path, provider=self.provider)
        except (DenseIndexError, EmbeddingValidationError, OSError, ValueError):
            return False
        return (
            receipt.backend == "dense"
            and receipt.generation_id == manifest.generation_id
            and receipt.manifest_sha256 == manifest.manifest_sha256
            and receipt.membership_sha256 == manifest.membership_sha256
            and receipt.member_count == len(manifest.membership)
            and receipt.fingerprint == self.fingerprint
            and receipt.artifact_sha256 == index.artifact_sha256
            and receipt.sentinel == f"dense:{len(index.entries)}:{index.artifact_sha256[:16]}"
            and receipt.visibility_verified
        )


class DenseChannel:
    name = "dense"

    def __init__(
        self,
        index: DenseIndex,
        *,
        provider: EmbeddingProvider,
        policy: Any,
        destination: EgressDestination = "local_generator",
        top_k: int = 40,
    ) -> None:
        self.index = index
        self.provider = provider
        self.policy = policy
        self.destination = destination
        self.top_k = top_k

    async def search(self, plan: Any, scope: ResolvedScope, snapshot: SnapshotRef, deadline: float) -> ChannelResult:
        query = plan if isinstance(plan, str) else getattr(plan, "query", None)
        if not isinstance(query, str) or not query.strip():
            return ChannelResult(channel=self.name, status="no_results", candidates=())
        if time.monotonic() >= deadline:
            return ChannelResult(channel=self.name, status="timeout", reason="deadline-expired")
        try:
            hits = self.index.search(
                query,
                provider=self.provider,
                scope=scope,
                snapshot=snapshot,
                destination=self.destination,
                top_k=self.top_k,
                deadline=deadline,
            )
            candidates = tuple(
                self.index.candidate_for_hit(hit, scope=scope, snapshot=snapshot, policy=self.policy)
                for hit in hits
            )
        except (TimeoutError, EmbeddingDeadlineExceeded):
            return ChannelResult(channel=self.name, status="timeout", reason="provider-timeout")
        except PermissionError:
            raise
        except Exception as exc:
            return ChannelResult(channel=self.name, status="error", reason=type(exc).__name__)
        if not candidates:
            return ChannelResult(channel=self.name, status="no_results", candidates=())
        return ChannelResult(channel=self.name, status="ok", candidates=candidates)


__all__ = [
    "DenseChannel",
    "DenseFingerprintMismatch",
    "DenseIndex",
    "DenseIndexError",
    "DenseProjectionWriter",
]
