"""Immutable publication manifests and projection receipts."""
from __future__ import annotations
from typing import Literal, Protocol
from pydantic import Field, field_validator, model_validator
from packages.evidence.ids import canonical_hash
from packages.evidence.schema import EvidenceModel
from packages.evidence.validation import require_sha256

ProjectionBackend = Literal["exact", "lexical", "dense", "graph"]


class GenerationMember(EvidenceModel):
    kind: Literal["object", "relation", "chunk"]
    evidence_uid: str
    revision_uid: str

    @field_validator("evidence_uid", "revision_uid")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return require_sha256(value)


class ProjectionSpec(EvidenceModel):
    backend: ProjectionBackend
    enabled: bool
    required: bool = True
    fingerprint: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_state(self):
        if not self.enabled and self.required:
            raise ValueError("disabled projection cannot be required")
        return self


class GenerationManifest(EvidenceModel):
    schema_version: Literal["generation-manifest-v1"] = "generation-manifest-v1"
    generation_id: str
    domain: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    corpus_id: str = Field(min_length=1)
    membership: tuple[GenerationMember, ...]
    projections: tuple[ProjectionSpec, ...]
    fingerprints: dict[str, str] = Field(default_factory=dict)

    @field_validator("generation_id")
    @classmethod
    def validate_generation(cls, value: str) -> str:
        return require_sha256(value, field_name="generation_id")

    @model_validator(mode="after")
    def canonical_shape(self):
        keys = [(member.kind, member.evidence_uid, member.revision_uid) for member in self.membership]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("membership must be sorted and unique")
        names = [projection.backend for projection in self.projections]
        if len(names) != len(set(names)):
            raise ValueError("projection backends must be unique")
        if not all(key and value for key, value in self.fingerprints.items()):
            raise ValueError("fingerprints require non-empty keys and values")
        return self

    @property
    def membership_sha256(self) -> str:
        return canonical_hash([
            "generation-membership-v1",
            [member.model_dump(mode="json") for member in self.membership],
        ])

    @property
    def manifest_sha256(self) -> str:
        return canonical_hash(["generation-manifest-v1", self.model_dump(mode="json")])

    @property
    def enabled_projections(self) -> tuple[ProjectionSpec, ...]:
        return tuple(projection for projection in self.projections if projection.enabled)

    @classmethod
    def create(
        cls,
        *,
        domain: str,
        scope_id: str,
        corpus_id: str,
        membership,
        projections,
        fingerprints,
    ) -> "GenerationManifest":
        members = tuple(sorted(membership, key=lambda member: (member.kind, member.evidence_uid, member.revision_uid)))
        projection_specs = tuple(sorted(projections, key=lambda projection: projection.backend))
        seed = {
            "domain": domain,
            "scope_id": scope_id,
            "corpus_id": corpus_id,
            "membership": [member.model_dump(mode="json") for member in members],
            "projections": [projection.model_dump(mode="json") for projection in projection_specs],
            "fingerprints": dict(sorted(fingerprints.items())),
        }
        generation_id = canonical_hash(["generation-id-v1", seed])
        return cls(
            generation_id=generation_id,
            domain=domain,
            scope_id=scope_id,
            corpus_id=corpus_id,
            membership=members,
            projections=projection_specs,
            fingerprints=dict(sorted(fingerprints.items())),
        )


class ProjectionReceipt(EvidenceModel):
    schema_version: Literal["projection-receipt-v1"] = "projection-receipt-v1"
    generation_id: str
    domain: str
    scope_id: str
    corpus_id: str
    backend: ProjectionBackend
    manifest_sha256: str
    membership_sha256: str
    member_count: int = Field(ge=0)
    fingerprint: str = Field(min_length=1)
    artifact_sha256: str
    visibility_verified: bool
    sentinel: str = Field(min_length=1)

    @field_validator("generation_id", "manifest_sha256", "membership_sha256", "artifact_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return require_sha256(value)


class ProjectionWriter(Protocol):
    backend: ProjectionBackend

    def build(self, manifest: GenerationManifest) -> ProjectionReceipt: ...
    def verify(self, manifest: GenerationManifest, receipt: ProjectionReceipt) -> bool: ...
