"""Snapshot-pinned Milvus retrieval and optional lazy pymilvus 2.3 adapter."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping, Sequence

from packages.evidence.ids import canonical_hash
from packages.evidence.policy import ResolvedScope, require_authorized
from packages.evidence.schema import (
    AuthorizedEvidenceView,
    ChannelScore,
    ChunkCandidate,
    EvidencePolicyMetadata,
    SnapshotRef,
)
from packages.indexing.vector_indexer import (
    MilvusClient,
    MilvusCollectionSpec,
    MilvusEndpointConfig,
    MilvusUnavailable,
    _identity_filter,
    collection_name,
)
from .candidate import BackendHit, ChannelResult
from .providers import EgressDestination, EmbeddingInput, EmbeddingProvider, validate_embedding_batch


class MilvusSearchError(RuntimeError):
    pass


class MilvusSearch:
    def __init__(
        self,
        store: Any,
        *,
        client: MilvusClient,
        endpoint: MilvusEndpointConfig,
        provider: EmbeddingProvider,
        manifest: Any,
    ) -> None:
        self.store = store
        self.client = client
        self.endpoint = endpoint
        self.provider = provider
        self.manifest = manifest
        self.collection_name = collection_name(endpoint, manifest)
        self.last_search_stats: dict[str, int | bool] = {
            "backend_limit": 0,
            "backend_rows": 0,
            "accepted_rows": 0,
            "truncated": False,
        }

    def _validate(self, scope: ResolvedScope, snapshot: SnapshotRef) -> None:
        if (scope.domain, scope.scope_id, scope.corpus_id) != (
            self.manifest.domain,
            self.manifest.scope_id,
            self.manifest.corpus_id,
        ):
            raise MilvusSearchError("resolved scope does not match Milvus generation")
        if (snapshot.domain, snapshot.scope_id, snapshot.snapshot_id, snapshot.manifest_sha256) != (
            self.manifest.domain,
            self.manifest.scope_id,
            self.manifest.generation_id,
            self.manifest.manifest_sha256,
        ):
            raise MilvusSearchError("snapshot does not match Milvus generation")
        dense = next((item for item in self.manifest.enabled_projections if item.backend == "dense"), None)
        if dense is None or dense.fingerprint != self.provider.fingerprint.digest:
            raise MilvusSearchError("embedding fingerprint mismatch; reindex required")

    def search(
        self,
        query: str,
        *,
        scope: ResolvedScope,
        snapshot: SnapshotRef,
        destination: EgressDestination,
        top_k: int,
        overfetch_factor: int = 3,
        deadline: float | None = None,
    ) -> tuple[BackendHit, ...]:
        if top_k < 1 or overfetch_factor < 1:
            raise ValueError("top_k and overfetch_factor must be positive")
        self._validate(scope, snapshot)
        if destination not in scope.allowed_destinations:
            raise PermissionError("query embedding destination is not authorized by resolved scope")
        query_batch = self.provider.encode_queries(
            (EmbeddingInput(item_id="query", text=query),),
            destination=destination,
            deadline=deadline,
        )
        query_batch = validate_embedding_batch(
            query_batch,
            expected_ids=("query",),
            expected_fingerprint=self.provider.fingerprint,
        )
        backend_limit = min(max(top_k * overfetch_factor, top_k), 200)
        filter_expr = _identity_filter(
            self.manifest.domain,
            self.manifest.scope_id,
            self.manifest.generation_id,
            self.provider.fingerprint.digest,
        )
        try:
            rows = self.client.search(
                self.collection_name,
                vector=query_batch.embeddings[0].vector,
                filter_expr=filter_expr,
                limit=backend_limit,
                metric={"cosine": "COSINE", "ip": "IP", "l2": "L2"}[
                    self.provider.fingerprint.metric
                ],
                output_fields=(
                    "chunk_uid",
                    "object_uid",
                    "object_revision_uid",
                    "generation_id",
                    "embedding_fingerprint",
                ),
            )
        except Exception as exc:
            raise MilvusUnavailable("advanced Milvus query is unavailable") from exc

        accepted: list[BackendHit] = []
        for backend_rank, raw in enumerate(rows, start=1):
            chunk_uid = str(raw.get("chunk_uid", ""))
            if not chunk_uid:
                continue
            catalog = self.store.connection.execute(
                "SELECT c.object_uid,c.object_revision_uid FROM snapshot_membership sm "
                "JOIN chunks c ON c.domain=sm.domain AND c.scope_id=sm.scope_id AND c.chunk_uid=sm.evidence_uid "
                "WHERE sm.domain=? AND sm.scope_id=? AND sm.snapshot_id=? AND sm.evidence_kind='chunk' "
                "AND sm.evidence_uid=?",
                (
                    self.manifest.domain,
                    self.manifest.scope_id,
                    self.manifest.generation_id,
                    chunk_uid,
                ),
            ).fetchone()
            if catalog is None:
                continue
            if str(raw.get("object_uid")) != str(catalog["object_uid"]):
                continue
            if str(raw.get("object_revision_uid")) != str(catalog["object_revision_uid"]):
                continue
            score = raw.get("score")
            accepted.append(
                BackendHit(
                    backend_key=f"milvus:{self.manifest.generation_id}:{chunk_uid}",
                    domain=self.manifest.domain,
                    scope_id=self.manifest.scope_id,
                    snapshot_id=self.manifest.generation_id,
                    logical_uid=chunk_uid,
                    raw_score=None if score is None else float(score),
                    metadata={
                        "backend_rank": backend_rank,
                        "requested_top_k": top_k,
                        "backend_limit": backend_limit,
                        "overfetch_factor": overfetch_factor,
                        "object_uid": catalog["object_uid"],
                        "object_revision_uid": catalog["object_revision_uid"],
                        "embedding_fingerprint": self.provider.fingerprint.digest,
                    },
                )
            )
        truncated = len(accepted) > top_k or len(rows) >= backend_limit
        self.last_search_stats = {
            "backend_limit": backend_limit,
            "backend_rows": len(rows),
            "accepted_rows": len(accepted),
            "truncated": truncated,
        }
        return tuple(accepted[:top_k])

    def candidate_for_hit(
        self,
        hit: BackendHit,
        *,
        scope: ResolvedScope,
        snapshot: SnapshotRef,
        policy: Any,
    ) -> ChunkCandidate:
        self._validate(scope, snapshot)
        if (hit.domain, hit.scope_id, hit.snapshot_id) != (
            self.manifest.domain,
            self.manifest.scope_id,
            self.manifest.generation_id,
        ):
            raise MilvusSearchError("backend hit does not match pinned generation")
        row = self.store.connection.execute(
            "SELECT c.object_uid,c.object_revision_uid,c.payload_json FROM snapshot_membership sm "
            "JOIN chunks c ON c.domain=sm.domain AND c.scope_id=sm.scope_id AND c.chunk_uid=sm.evidence_uid "
            "WHERE sm.domain=? AND sm.scope_id=? AND sm.snapshot_id=? AND sm.evidence_kind='chunk' "
            "AND sm.evidence_uid=?",
            (
                self.manifest.domain,
                self.manifest.scope_id,
                self.manifest.generation_id,
                hit.logical_uid,
            ),
        ).fetchone()
        if row is None:
            raise MilvusSearchError("Milvus candidate is not authoritative snapshot membership")
        payload = json.loads(row["payload_json"])
        policy_payload = payload.get("policy") or {}
        view = AuthorizedEvidenceView(
            evidence_uid=hit.logical_uid,
            domain=self.manifest.domain,
            scope_id=self.manifest.scope_id,
            source_instances=tuple(policy_payload.get("source_instances", ())),
            policy=EvidencePolicyMetadata.model_validate(policy_payload),
        )
        require_authorized(policy.authorize_evidence(view, scope, "caller"))
        return ChunkCandidate(
            candidate_id=canonical_hash(
                ["candidate-v1", "milvus", self.manifest.generation_id, hit.logical_uid]
            ),
            domain=self.manifest.domain,
            scope_id=self.manifest.scope_id,
            snapshot=snapshot,
            target_object_uid=row["object_uid"],
            authorized_view=view,
            provenance=(),
            channel_scores=(
                ChannelScore(
                    channel="dense",
                    rank=int(hit.metadata.get("backend_rank", 1)),
                    raw_score=hit.raw_score,
                    score_kind=self.provider.fingerprint.metric,
                ),
            ),
            chunk_uid=hit.logical_uid,
            object_uid=row["object_uid"],
        )


class MilvusChannel:
    name = "dense"

    def __init__(
        self,
        searcher: MilvusSearch,
        *,
        policy: Any,
        destination: EgressDestination = "embedding_provider",
        top_k: int = 40,
        overfetch_factor: int = 3,
    ) -> None:
        self.searcher = searcher
        self.policy = policy
        self.destination = destination
        self.top_k = top_k
        self.overfetch_factor = overfetch_factor

    async def search(self, plan: Any, scope: ResolvedScope, snapshot: SnapshotRef, deadline: float) -> ChannelResult:
        query = plan if isinstance(plan, str) else getattr(plan, "query", None)
        if not isinstance(query, str) or not query.strip():
            return ChannelResult(channel=self.name, status="no_results", candidates=())
        if time.monotonic() >= deadline:
            return ChannelResult(channel=self.name, status="timeout", reason="deadline-expired")
        try:
            hits = self.searcher.search(
                query,
                scope=scope,
                snapshot=snapshot,
                destination=self.destination,
                top_k=self.top_k,
                overfetch_factor=self.overfetch_factor,
                deadline=deadline,
            )
            candidates = tuple(
                self.searcher.candidate_for_hit(
                    hit, scope=scope, snapshot=snapshot, policy=self.policy
                )
                for hit in hits
            )
        except MilvusUnavailable:
            return ChannelResult(channel=self.name, status="error", reason="backend-unavailable")
        except PermissionError:
            raise
        except Exception as exc:
            return ChannelResult(channel=self.name, status="error", reason=type(exc).__name__)
        if not candidates:
            return ChannelResult(channel=self.name, status="no_results", candidates=())
        return ChannelResult(
            channel=self.name,
            status="ok",
            candidates=candidates,
            truncated=bool(self.searcher.last_search_stats.get("truncated", False)),
        )


class Pymilvus23Adapter:
    """Lazy optional adapter for the pinned 2.3.x client family.

    Import/connection happen only in ``connect``. No URI or credential is inferred
    from legacy configuration, and no collection-drop/delete API is exposed.
    """

    def __init__(self, *, alias: str, endpoint: MilvusEndpointConfig) -> None:
        self.alias = alias
        self.endpoint = endpoint

    @classmethod
    def connect(cls, endpoint: MilvusEndpointConfig, *, alias: str = "advanced") -> "Pymilvus23Adapter":
        try:
            import pymilvus
            from pymilvus import connections
        except ImportError as exc:
            raise MilvusUnavailable("pymilvus optional dependency is not installed") from exc
        observed_client = str(getattr(pymilvus, "__version__", "unknown"))
        if observed_client.lstrip("v") != endpoint.expected_client_version.lstrip("v"):
            raise MilvusUnavailable(
                f"pymilvus version mismatch: expected {endpoint.expected_client_version}, observed {observed_client}"
            )
        kwargs: dict[str, Any] = {"alias": alias, "uri": endpoint.uri}
        if endpoint.token_env:
            token = os.getenv(endpoint.token_env)
            if not token:
                raise MilvusUnavailable("configured advanced Milvus credential is unavailable")
            kwargs["token"] = token
        try:
            connections.connect(**kwargs)
        except Exception as exc:
            raise MilvusUnavailable("advanced Milvus connection failed") from exc
        return cls(alias=alias, endpoint=endpoint)

    def _imports(self):
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility
        return Collection, CollectionSchema, DataType, FieldSchema, utility

    def server_version(self) -> str:
        *_, utility = self._imports()
        return str(utility.get_server_version(using=self.alias))

    def collection_exists(self, collection_name: str) -> bool:
        *_, utility = self._imports()
        return bool(utility.has_collection(collection_name, using=self.alias))

    def create_collection(self, spec: MilvusCollectionSpec) -> None:
        Collection, CollectionSchema, DataType, FieldSchema, _ = self._imports()
        dtype = {"VARCHAR": DataType.VARCHAR, "FLOAT_VECTOR": DataType.FLOAT_VECTOR}
        fields = []
        for field in spec.fields:
            kwargs: dict[str, Any] = {
                "name": field.name,
                "dtype": dtype[field.kind],
                "is_primary": field.primary,
            }
            if field.primary:
                kwargs["auto_id"] = False
            if field.max_length is not None:
                kwargs["max_length"] = field.max_length
            if field.dimension is not None:
                kwargs["dim"] = field.dimension
            fields.append(FieldSchema(**kwargs))
        schema = CollectionSchema(fields=fields, enable_dynamic_field=False)
        collection = Collection(spec.collection_name, schema=schema, using=self.alias)
        collection.create_index(
            field_name="vector",
            index_params={
                "index_type": "FLAT",
                "metric_type": spec.metric,
                "params": {},
            },
        )

    def _collection(self, name: str):
        Collection, *_ = self._imports()
        return Collection(name, using=self.alias)

    def describe_collection(self, collection_name: str) -> Mapping[str, Any]:
        Collection, _, DataType, _, _ = self._imports()
        collection = Collection(collection_name, using=self.alias)
        fields = []
        for field in collection.schema.fields:
            kind = "FLOAT_VECTOR" if field.dtype == DataType.FLOAT_VECTOR else "VARCHAR"
            fields.append(
                {
                    "name": field.name,
                    "kind": kind,
                    "max_length": field.params.get("max_length"),
                    "dimension": field.params.get("dim"),
                    "primary": bool(field.is_primary),
                }
            )
        indexes = list(collection.indexes)
        metric = indexes[0].params.get("metric_type") if indexes else None
        return {"fields": fields, "metric": metric}

    def upsert(self, collection_name: str, records: Sequence[Mapping[str, Any]]) -> int:
        result = self._collection(collection_name).upsert(list(records))
        count = getattr(result, "upsert_count", None)
        return len(records) if count is None else int(count)

    def flush(self, collection_name: str) -> None:
        self._collection(collection_name).flush()

    def load(self, collection_name: str) -> None:
        self._collection(collection_name).load()

    def query(self, collection_name: str, *, filter_expr: str, output_fields: Sequence[str], limit: int):
        return self._collection(collection_name).query(
            expr=filter_expr,
            output_fields=list(output_fields),
            limit=limit,
            consistency_level="Strong",
        )

    def search(
        self,
        collection_name: str,
        *,
        vector: Sequence[float],
        filter_expr: str,
        limit: int,
        metric: str,
        output_fields: Sequence[str],
    ):
        result = self._collection(collection_name).search(
            data=[list(vector)],
            anns_field="vector",
            param={"metric_type": metric, "params": {}},
            limit=limit,
            expr=filter_expr,
            output_fields=list(output_fields),
            consistency_level="Strong",
        )
        rows = []
        for hit in result[0] if result else []:
            entity = getattr(hit, "entity", None)
            item = {field: entity.get(field) for field in output_fields} if entity is not None else {}
            item["score"] = float(getattr(hit, "score", getattr(hit, "distance", 0.0)))
            rows.append(item)
        return rows


__all__ = ["MilvusChannel", "MilvusSearch", "MilvusSearchError", "Pymilvus23Adapter"]
