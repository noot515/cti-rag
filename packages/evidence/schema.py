"""Domain-neutral evidence contracts for advanced retrieval."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from .validation import normalize_utc_datetime, require_sha256


class EvidenceModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class LifecycleState(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    REVOKED = "revoked"
    DELETED = "deleted"


class SourceRef(EvidenceModel):
    domain: str = Field(min_length=1)
    source_instance: str = Field(min_length=1)
    source_object_id: str = Field(min_length=1)
    upstream_origin: str = Field(min_length=1)
    source_uri: str | None = None
    raw_payload_sha256: str
    source_snapshot_id: str = Field(min_length=1)
    normalizer_version: str = Field(min_length=1)

    @field_validator("raw_payload_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return require_sha256(value, field_name="raw_payload_sha256")


class ExternalIdentifier(EvidenceModel):
    namespace: str = Field(min_length=1)
    value: str = Field(min_length=1)
    taxonomy: str | None = None
    version: str | None = None
    domain: str | None = None


class Qualifier(EvidenceModel):
    name: str = Field(min_length=1)
    value: JsonValue


class EvidencePolicyMetadata(EvidenceModel):
    source_instances: tuple[str, ...] = ()
    marking_refs: tuple[str, ...] = ()
    dissemination: tuple[str, ...] = ()
    granular_selectors: tuple[str, ...] = ()
    unresolved_markings: bool = False


class EvidenceObject(EvidenceModel):
    uid: str
    revision_uid: str
    domain: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    object_type: str = Field(min_length=1)
    name: str | None = None
    description: str | None = None
    external_ids: tuple[ExternalIdentifier, ...] = ()
    aliases: tuple[str, ...] = ()
    source_refs: tuple[SourceRef, ...] = ()
    created_at: datetime | None = None
    modified_at: datetime | None = None
    observed_at: datetime | None = None
    lifecycle_state: LifecycleState = LifecycleState.ACTIVE
    raw_payload_ref: str | None = None
    extension_type: str | None = None
    policy: EvidencePolicyMetadata = Field(default_factory=EvidencePolicyMetadata)

    @field_validator("uid", "revision_uid")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:
        return require_sha256(value, field_name=info.field_name)

    @field_validator("created_at", "modified_at", "observed_at", mode="before")
    @classmethod
    def normalize_timestamp(cls, value):
        return normalize_utc_datetime(value)

    @model_validator(mode="after")
    def source_domains_match(self) -> "EvidenceObject":
        if any(ref.domain != self.domain for ref in self.source_refs):
            raise ValueError("all source_refs must belong to the evidence object's domain")
        return self


class EvidenceRelation(EvidenceModel):
    uid: str
    revision_uid: str
    domain: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    source_object_uid: str
    target_object_uid: str
    original_relation: str = Field(min_length=1)
    normalized_relation: str = Field(min_length=1)
    direction: Literal["forward", "reverse", "bidirectional"] = "forward"
    assertion_kind: str = Field(min_length=1)
    evidence_refs: tuple[SourceRef, ...] = ()
    qualifiers: tuple[Qualifier, ...] = ()
    source_field_path: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    applicability: tuple[Qualifier, ...] = ()
    lifecycle_state: LifecycleState = LifecycleState.ACTIVE
    extension_type: str | None = None
    policy: EvidencePolicyMetadata = Field(default_factory=EvidencePolicyMetadata)

    @field_validator("uid", "revision_uid", "source_object_uid", "target_object_uid")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:
        return require_sha256(value, field_name=info.field_name)

    @field_validator("valid_from", "valid_until", mode="before")
    @classmethod
    def normalize_timestamp(cls, value):
        return normalize_utc_datetime(value)

    @model_validator(mode="after")
    def validate_temporal_range(self) -> "EvidenceRelation":
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must not precede valid_from")
        if any(ref.domain != self.domain for ref in self.evidence_refs):
            raise ValueError("all evidence_refs must belong to the relation domain")
        return self


class EvidenceChunk(EvidenceModel):
    uid: str
    object_uid: str
    object_revision_uid: str
    domain: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    chunker_fingerprint: str = Field(min_length=1)
    section_path: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    text: str
    content_hash: str
    token_count: int = Field(ge=0)
    tokenizer_fingerprint: str = Field(min_length=1)
    source_refs: tuple[SourceRef, ...] = ()
    policy: EvidencePolicyMetadata = Field(default_factory=EvidencePolicyMetadata)
    extension_type: str | None = None

    @field_validator("uid", "object_uid", "object_revision_uid", "content_hash")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:
        return require_sha256(value, field_name=info.field_name)


class EvidencePath(EvidenceModel):
    path_id: str
    ordered_node_uids: tuple[str, ...]
    ordered_relation_revision_uids: tuple[str, ...]
    traversal_directions: tuple[Literal["forward", "reverse"], ...]
    source_refs: tuple[SourceRef, ...] = ()
    domains_traversed: tuple[str, ...]

    @field_validator("path_id")
    @classmethod
    def validate_path_id(cls, value: str) -> str:
        return require_sha256(value, field_name="path_id")

    @field_validator("ordered_node_uids", "ordered_relation_revision_uids")
    @classmethod
    def validate_uid_sequence(cls, values: tuple[str, ...], info) -> tuple[str, ...]:
        for value in values:
            require_sha256(value, field_name=info.field_name)
        return values

    @model_validator(mode="after")
    def path_shape_is_consistent(self) -> "EvidencePath":
        edge_count = len(self.ordered_relation_revision_uids)
        if len(self.ordered_node_uids) != edge_count + 1:
            raise ValueError("a path must contain exactly one more node than relations")
        if len(self.traversal_directions) != edge_count:
            raise ValueError("each relation revision needs one traversal direction")
        return self


class ChannelScore(EvidenceModel):
    rank: int = Field(ge=1)
    raw_score: float | None = None
    score_kind: str = Field(min_length=1)


class AuthorizedEvidenceView(EvidenceModel):
    evidence_uid: str
    domain: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    source_instances: tuple[str, ...] = ()
    policy: EvidencePolicyMetadata = Field(default_factory=EvidencePolicyMetadata)

    @field_validator("evidence_uid")
    @classmethod
    def validate_evidence_uid(cls, value: str) -> str:
        return require_sha256(value, field_name="evidence_uid")


class RetrievalCandidate(EvidenceModel):
    candidate_id: str
    kind: Literal["chunk", "object", "path"]
    domain: str = Field(min_length=1)
    object_uid: str | None = None
    chunk_uid: str | None = None
    path_id: str | None = None
    authorized_view: AuthorizedEvidenceView
    provenance: tuple[SourceRef, ...] = ()
    channel_scores: dict[str, ChannelScore] = Field(default_factory=dict)
    fused_score: float | None = None
    rerank_score: float | None = None
    snapshot_id: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def reference_matches_kind(self) -> "RetrievalCandidate":
        refs = {
            "object": self.object_uid,
            "chunk": self.chunk_uid,
            "path": self.path_id,
        }
        if refs[self.kind] is None:
            raise ValueError(f"{self.kind} candidate requires its matching reference")
        return self


class RetrievalRequest(EvidenceModel):
    query: str = Field(min_length=1, max_length=8192)
    corpus_id: str = Field(min_length=1)
    top_k: int = Field(default=12, ge=1, le=50)
    max_graph_hops: int = Field(default=2, ge=0, le=3)
    response_mode: Literal["summary", "full"] = "summary"


class CitationRecord(EvidenceModel):
    label: str = Field(min_length=1)
    evidence_uid: str
    domain: str = Field(min_length=1)
    source_uri: str | None = None
    emitted_start: int = Field(ge=0)
    emitted_end: int = Field(ge=0)
    object_revision_uid: str | None = None
    relation_revision_uid: str | None = None

    @model_validator(mode="after")
    def valid_offsets(self) -> "CitationRecord":
        if self.emitted_end < self.emitted_start:
            raise ValueError("citation end must not precede start")
        return self


class RetrievalResult(EvidenceModel):
    retrieval_run_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    status: Literal["ok", "no_evidence", "partial"]
    candidates: tuple[RetrievalCandidate, ...] = ()
    answer_context: str = ""
    citations: tuple[CitationRecord, ...] = ()
    authorized_trace: tuple[str, ...] = ()
    truncated: bool = False
    timings_ms: dict[str, float] = Field(default_factory=dict)
    model_fingerprints: dict[str, str] = Field(default_factory=dict)


__all__ = [
    "AuthorizedEvidenceView",
    "ChannelScore",
    "CitationRecord",
    "EvidenceChunk",
    "EvidenceModel",
    "EvidenceObject",
    "EvidencePath",
    "EvidencePolicyMetadata",
    "EvidenceRelation",
    "ExternalIdentifier",
    "LifecycleState",
    "Qualifier",
    "RetrievalCandidate",
    "RetrievalRequest",
    "RetrievalResult",
    "SourceRef",
]
