"""Non-destructive generation-scoped Milvus projection for the advanced path.

The projection depends only on an injected client protocol. Importing this module does
not import pymilvus, connect to a service, or inspect legacy Milvus configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.evidence.ids import canonical_hash
from packages.evidence.policy import ResolvedScope, require_authorized
from packages.evidence.schema import AuthorizedEvidenceView, EvidencePolicyMetadata
from packages.indexing.manifests import GenerationManifest, ProjectionReceipt
from packages.retrieval.providers import (
    EgressDestination,
    EmbeddingInput,
    EmbeddingProvider,
    EmbeddingValidationError,
    validate_embedding_batch,
)


class MilvusProjectionError(RuntimeError):
    pass


class MilvusSchemaMismatch(MilvusProjectionError):
    pass


class MilvusVisibilityError(MilvusProjectionError):
    pass


class MilvusUnavailable(MilvusProjectionError):
    pass


class MilvusFieldOverflow(MilvusProjectionError):
    pass


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MilvusEndpointConfig(_FrozenModel):
    uri: str = Field(min_length=1)
    deployment_id: str = Field(min_length=1)
    collection_prefix: str = Field(default="adv_cti", min_length=1, max_length=48)
    expected_server_version: str = Field(default="2.3.4", min_length=1)
    expected_client_version: str = Field(default="2.3.7", min_length=1)
    token_env: str | None = None

    @model_validator(mode="after")
    def advanced_only(self) -> "MilvusEndpointConfig":
        parsed = urlparse(self.uri)
        if parsed.scheme not in {"http", "https", "tcp"} or not parsed.hostname:
            raise ValueError("advanced Milvus URI must be an explicit http/https/tcp endpoint")
        if not self.deployment_id.startswith("advanced-"):
            raise ValueError("Milvus deployment_id must explicitly identify an advanced deployment")
        if self.collection_prefix.startswith(("kb_", "legacy_")):
            raise ValueError("advanced collection prefix must not use a legacy namespace")
        if self.token_env is not None and not self.token_env.strip():
            raise ValueError("Milvus token_env must be a non-empty environment variable name")
        return self


@dataclass(frozen=True)
class MilvusFieldSpec:
    name: str
    kind: str
    max_length: int | None = None
    dimension: int | None = None
    primary: bool = False


@dataclass(frozen=True)
class MilvusCollectionSpec:
    collection_name: str
    metric: str
    fields: tuple[MilvusFieldSpec, ...]

    @property
    def schema_fingerprint(self) -> str:
        return canonical_hash(
            [
                "advanced-milvus-schema-v1",
                self.collection_name,
                self.metric,
                [field.__dict__ for field in self.fields],
            ]
        )


class MilvusClient(Protocol):
    def server_version(self) -> str: ...
    def collection_exists(self, collection_name: str) -> bool: ...
    def create_collection(self, spec: MilvusCollectionSpec) -> None: ...
    def describe_collection(self, collection_name: str) -> Mapping[str, Any]: ...
    def upsert(self, collection_name: str, records: Sequence[Mapping[str, Any]]) -> int: ...
    def flush(self, collection_name: str) -> None: ...
    def load(self, collection_name: str) -> None: ...
    def query(
        self,
        collection_name: str,
        *,
        filter_expr: str,
        output_fields: Sequence[str],
        limit: int,
    ) -> Sequence[Mapping[str, Any]]: ...
    def search(
        self,
        collection_name: str,
        *,
        vector: Sequence[float],
        filter_expr: str,
        limit: int,
        metric: str,
        output_fields: Sequence[str],
    ) -> Sequence[Mapping[str, Any]]: ...


_MAX_TEXT_BYTES = {
    "chunk_uid": 64,
    "domain": 128,
    "scope_id": 256,
    "object_uid": 64,
    "object_revision_uid": 64,
    "generation_id": 64,
    "manifest_sha256": 64,
    "embedding_fingerprint": 64,
}


def _validate_utf8(name: str, value: str) -> str:
    limit = _MAX_TEXT_BYTES[name]
    observed = len(value.encode("utf-8"))
    if observed > limit:
        raise MilvusFieldOverflow(
            f"Milvus field {name} exceeds {limit} UTF-8 bytes (observed {observed})"
        )
    return value


def _metric(provider: EmbeddingProvider) -> str:
    return {"cosine": "COSINE", "ip": "IP", "l2": "L2"}[provider.fingerprint.metric]


def collection_name(endpoint: MilvusEndpointConfig, manifest: GenerationManifest) -> str:
    scope_hash = sha256(f"{manifest.domain}\x00{manifest.scope_id}".encode("utf-8")).hexdigest()[:12]
    name = f"{endpoint.collection_prefix}_{scope_hash}_{manifest.generation_id[:20]}"
    if len(name.encode("utf-8")) > 255:
        raise MilvusFieldOverflow("generated Milvus collection name exceeds 255 UTF-8 bytes")
    return name


def collection_spec(
    endpoint: MilvusEndpointConfig,
    manifest: GenerationManifest,
    provider: EmbeddingProvider,
) -> MilvusCollectionSpec:
    return MilvusCollectionSpec(
        collection_name=collection_name(endpoint, manifest),
        metric=_metric(provider),
        fields=(
            MilvusFieldSpec("chunk_uid", "VARCHAR", max_length=64, primary=True),
            MilvusFieldSpec("domain", "VARCHAR", max_length=128),
            MilvusFieldSpec("scope_id", "VARCHAR", max_length=256),
            MilvusFieldSpec("object_uid", "VARCHAR", max_length=64),
            MilvusFieldSpec("object_revision_uid", "VARCHAR", max_length=64),
            MilvusFieldSpec("generation_id", "VARCHAR", max_length=64),
            MilvusFieldSpec("manifest_sha256", "VARCHAR", max_length=64),
            MilvusFieldSpec("embedding_fingerprint", "VARCHAR", max_length=64),
            MilvusFieldSpec("vector", "FLOAT_VECTOR", dimension=provider.fingerprint.dimensions),
        ),
    )


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


def _evidence_view(row: Mapping[str, Any], manifest: GenerationManifest) -> AuthorizedEvidenceView:
    policy_payload = row["payload"].get("policy") or {}
    return AuthorizedEvidenceView(
        evidence_uid=str(row["chunk_uid"]),
        domain=manifest.domain,
        scope_id=manifest.scope_id,
        source_instances=tuple(policy_payload.get("source_instances", ())),
        policy=EvidencePolicyMetadata.model_validate(policy_payload),
    )


def _schema_matches(description: Mapping[str, Any], expected: MilvusCollectionSpec) -> bool:
    if description.get("schema_fingerprint") == expected.schema_fingerprint:
        return True
    observed_fields = description.get("fields")
    if not isinstance(observed_fields, Sequence):
        return False
    normalized = []
    for field in observed_fields:
        if not isinstance(field, Mapping):
            return False
        normalized.append(
            MilvusFieldSpec(
                name=str(field.get("name")),
                kind=str(field.get("kind")),
                max_length=field.get("max_length"),
                dimension=field.get("dimension"),
                primary=bool(field.get("primary", False)),
            )
        )
    return tuple(normalized) == expected.fields and str(description.get("metric")) == expected.metric


class MilvusProjection:
    """Trusted generation writer; never drops or recreates an existing collection."""

    backend = "dense"

    def __init__(
        self,
        store: Any,
        *,
        client: MilvusClient,
        endpoint: MilvusEndpointConfig,
        provider: EmbeddingProvider,
        scope: ResolvedScope,
        policy: Any,
        destination: EgressDestination = "embedding_provider",
    ) -> None:
        self.store = store
        self.client = client
        self.endpoint = endpoint
        self.provider = provider
        self.scope = scope
        self.policy = policy
        self.destination = destination
        self.fingerprint = provider.fingerprint.digest

    def _validate_manifest(self, manifest: GenerationManifest) -> MilvusCollectionSpec:
        if (manifest.domain, manifest.scope_id, manifest.corpus_id) != (
            self.scope.domain,
            self.scope.scope_id,
            self.scope.corpus_id,
        ):
            raise MilvusProjectionError("resolved scope does not match Milvus generation")
        dense = next((item for item in manifest.enabled_projections if item.backend == "dense"), None)
        if dense is None:
            raise MilvusProjectionError("generation does not enable dense projection")
        if dense.fingerprint != self.provider.fingerprint.digest:
            raise MilvusProjectionError("embedding fingerprint mismatch; reindex required")
        return collection_spec(self.endpoint, manifest, self.provider)

    def _verify_server(self) -> None:
        try:
            observed = self.client.server_version()
        except Exception as exc:
            raise MilvusUnavailable("cannot verify advanced Milvus server version") from exc
        if observed.lstrip("v") != self.endpoint.expected_server_version.lstrip("v"):
            raise MilvusProjectionError(
                f"Milvus server version mismatch: expected {self.endpoint.expected_server_version}, observed {observed}"
            )

    def build(self, manifest: GenerationManifest) -> ProjectionReceipt:
        spec = self._validate_manifest(manifest)
        self._verify_server()
        rows = _chunk_rows(self.store, manifest)
        inputs: list[EmbeddingInput] = []
        metadata: dict[str, dict[str, Any]] = {}
        for row in rows:
            require_authorized(
                self.policy.authorize_evidence(
                    _evidence_view(row, manifest), self.scope, self.destination
                )
            )
            inputs.append(EmbeddingInput(item_id=row["chunk_uid"], text=str(row["payload"].get("text", ""))))
            metadata[row["chunk_uid"]] = row

        batch = self.provider.encode_documents(inputs, destination=self.destination)
        batch = validate_embedding_batch(
            batch,
            expected_ids=(item.item_id for item in inputs),
            expected_fingerprint=self.provider.fingerprint,
        )

        records = []
        for item in batch.embeddings:
            row = metadata[item.item_id]
            record = {
                "chunk_uid": _validate_utf8("chunk_uid", item.item_id),
                "domain": _validate_utf8("domain", manifest.domain),
                "scope_id": _validate_utf8("scope_id", manifest.scope_id),
                "object_uid": _validate_utf8("object_uid", row["object_uid"]),
                "object_revision_uid": _validate_utf8(
                    "object_revision_uid", row["object_revision_uid"]
                ),
                "generation_id": _validate_utf8("generation_id", manifest.generation_id),
                "manifest_sha256": _validate_utf8("manifest_sha256", manifest.manifest_sha256),
                "embedding_fingerprint": _validate_utf8(
                    "embedding_fingerprint", self.provider.fingerprint.digest
                ),
                "vector": list(item.vector),
            }
            if any(not math.isfinite(value) for value in item.vector):
                raise EmbeddingValidationError("Milvus write contains non-finite vector")
            records.append(record)

        try:
            if self.client.collection_exists(spec.collection_name):
                description = self.client.describe_collection(spec.collection_name)
                if not _schema_matches(description, spec):
                    raise MilvusSchemaMismatch(
                        "existing advanced collection has incompatible schema; destructive recreate is forbidden"
                    )
            else:
                self.client.create_collection(spec)

            if records:
                written = self.client.upsert(spec.collection_name, records)
                if written != len(records):
                    raise MilvusProjectionError(
                        f"Milvus upsert count mismatch: expected {len(records)}, observed {written}"
                    )
            self.client.flush(spec.collection_name)
            self.client.load(spec.collection_name)
            sentinel = records[0]["chunk_uid"] if records else manifest.generation_id
            visible = self.client.query(
                spec.collection_name,
                filter_expr=_identity_filter(
                    manifest.domain,
                    manifest.scope_id,
                    manifest.generation_id,
                    self.provider.fingerprint.digest,
                    chunk_uid=sentinel if records else None,
                ),
                output_fields=("chunk_uid", "generation_id", "embedding_fingerprint"),
                limit=1,
            )
            if records and not visible:
                raise MilvusVisibilityError("Milvus generation is not visible after flush/load")
        except MilvusProjectionError:
            raise
        except Exception as exc:
            raise MilvusUnavailable("advanced Milvus projection is unavailable") from exc

        artifact_sha256 = canonical_hash(
            [
                "advanced-milvus-projection-v1",
                self.endpoint.deployment_id,
                spec.collection_name,
                spec.schema_fingerprint,
                manifest.manifest_sha256,
                manifest.membership_sha256,
                self.provider.fingerprint.digest,
            ]
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
            fingerprint=self.provider.fingerprint.digest,
            artifact_sha256=artifact_sha256,
            visibility_verified=True,
            sentinel=f"milvus:{spec.collection_name}:{sentinel}",
        )

    def verify(self, manifest: GenerationManifest, receipt: ProjectionReceipt) -> bool:
        try:
            spec = self._validate_manifest(manifest)
            self._verify_server()
            if not self.client.collection_exists(spec.collection_name):
                return False
            if not _schema_matches(self.client.describe_collection(spec.collection_name), spec):
                return False
            if receipt.fingerprint != self.provider.fingerprint.digest:
                return False
            expected_artifact = canonical_hash(
                [
                    "advanced-milvus-projection-v1",
                    self.endpoint.deployment_id,
                    spec.collection_name,
                    spec.schema_fingerprint,
                    manifest.manifest_sha256,
                    manifest.membership_sha256,
                    self.provider.fingerprint.digest,
                ]
            )
            has_chunks = any(member.kind == "chunk" for member in manifest.membership)
            sentinel_prefix = f"milvus:{spec.collection_name}:"
            if not receipt.sentinel.startswith(sentinel_prefix):
                return False
            sentinel_value = receipt.sentinel[len(sentinel_prefix):]
            visible = self.client.query(
                spec.collection_name,
                filter_expr=_identity_filter(
                    manifest.domain,
                    manifest.scope_id,
                    manifest.generation_id,
                    self.provider.fingerprint.digest,
                    chunk_uid=sentinel_value if has_chunks else None,
                ),
                output_fields=("chunk_uid",),
                limit=1,
            )
            return (
                receipt.backend == "dense"
                and receipt.generation_id == manifest.generation_id
                and receipt.manifest_sha256 == manifest.manifest_sha256
                and receipt.membership_sha256 == manifest.membership_sha256
                and receipt.member_count == len(manifest.membership)
                and receipt.artifact_sha256 == expected_artifact
                and receipt.visibility_verified
                and (bool(visible) if has_chunks else True)
            )
        except Exception:
            return False


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _identity_filter(
    domain: str,
    scope_id: str,
    generation_id: str,
    embedding_fingerprint: str,
    *,
    chunk_uid: str | None = None,
) -> str:
    parts = [
        f'domain == "{_quote(domain)}"',
        f'scope_id == "{_quote(scope_id)}"',
        f'generation_id == "{_quote(generation_id)}"',
        f'embedding_fingerprint == "{_quote(embedding_fingerprint)}"',
    ]
    if chunk_uid is not None:
        parts.append(f'chunk_uid == "{_quote(chunk_uid)}"')
    return " and ".join(parts)


__all__ = [
    "MilvusClient",
    "MilvusCollectionSpec",
    "MilvusEndpointConfig",
    "MilvusFieldOverflow",
    "MilvusFieldSpec",
    "MilvusProjection",
    "MilvusProjectionError",
    "MilvusSchemaMismatch",
    "MilvusUnavailable",
    "MilvusVisibilityError",
    "collection_name",
    "collection_spec",
    "_identity_filter",
]
