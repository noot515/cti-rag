"""Generic retrieval candidate, target-projection and channel contracts."""
from __future__ import annotations

from typing import Any, Literal, Protocol
from pydantic import Field, field_validator, model_validator

from packages.evidence.policy import ResolvedScope
from packages.evidence.schema import (
    Candidate,
    ChunkCandidate,
    EvidenceModel,
    ObjectCandidate,
    PathCandidate,
    SnapshotRef,
)
from packages.evidence.validation import require_sha256


class BackendHit(EvidenceModel):
    """Untrusted backend output before policy resolution and candidate construction."""
    backend_key: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    logical_uid: str
    raw_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("logical_uid")
    @classmethod
    def validate_uid(cls, value: str) -> str:
        return require_sha256(value, field_name="logical_uid")


class ChannelResult(EvidenceModel):
    channel: str = Field(min_length=1)
    status: Literal["ok", "no_results", "timeout", "error", "not_run"]
    candidates: tuple[Candidate, ...] = ()
    truncated: bool = False
    reason: str | None = None

    @model_validator(mode="after")
    def status_matches_payload(self) -> "ChannelResult":
        if self.status in {"timeout", "error", "not_run"} and not self.reason:
            raise ValueError("non-success channel statuses require a reason")
        if self.status == "no_results" and self.candidates:
            raise ValueError("no_results channel status cannot contain candidates")
        return self


class Channel(Protocol):
    name: str

    async def search(
        self,
        plan: Any,
        scope: ResolvedScope,
        snapshot: SnapshotRef,
        deadline: float,
    ) -> ChannelResult: ...


class TargetObjectRef(EvidenceModel):
    """Explicit answer-object identity derived from evidence, never an evidence alias."""
    object_uid: str
    object_revision_uid: str | None = None
    object_type: str | None = None

    @field_validator("object_uid", "object_revision_uid")
    @classmethod
    def validate_target_ids(cls, value: str | None, info):
        if value is None:
            return None
        return require_sha256(value, field_name=info.field_name)


class TargetProjection(EvidenceModel):
    """Associates one evidence candidate with zero or more explicit answer objects."""
    candidate_id: str
    evidence_kind: Literal["object", "chunk", "path"]
    targets: tuple[TargetObjectRef, ...]
    projection_kind: Literal["direct_object", "chunk_parent", "path_terminal"]

    @field_validator("candidate_id")
    @classmethod
    def validate_candidate_id(cls, value: str) -> str:
        return require_sha256(value, field_name="candidate_id")


__all__ = [
    "BackendHit",
    "Candidate",
    "Channel",
    "ChannelResult",
    "ChunkCandidate",
    "ObjectCandidate",
    "PathCandidate",
    "TargetObjectRef",
    "TargetProjection",
]
