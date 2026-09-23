"""Immutable canonical evidence contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from .errors import ValidationError
from .identity import (
    ComponentFingerprint,
    make_artifact_uid,
    make_assertion_uid,
    make_entity_uid,
    make_object_uid,
    make_passage_uid,
    make_representation_uid,
    make_revision_uid,
    sha256_hex,
)
from .policy import PolicyLabels
from .provenance import Lineage, Locator, ProvenanceRef, locator_to_data
from .temporal import TemporalMetadata, ensure_utc


class ArtifactType(str, Enum):
    TEXT = "text"
    JSON = "json"
    TABLE = "table"
    TEI = "tei"
    BINARY_DERIVATIVE = "binary_derivative"


class RepresentationKind(str, Enum):
    LEXICAL = "lexical"
    DENSE = "dense"
    ENTITY = "entity"
    GRAPH = "graph"


class EpistemicKind(str, Enum):
    SOURCE_CLAIM = "source_claim"
    OBSERVATION = "observation"
    EXTRACTION = "extraction"
    INTERPRETATION = "interpretation"
    INFERENCE = "inference"


@dataclass(frozen=True)
class EpistemicMetadata:
    kind: EpistemicKind
    method: Optional[str] = None
    confidence: Optional[float] = None

    def __post_init__(self) -> None:
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValidationError("epistemic confidence must be in [0, 1]")


@dataclass(frozen=True)
class IdentityAttribute:
    name: str
    value: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("identity attribute name must be non-empty")


@dataclass(frozen=True)
class EntityRef:
    namespace: str
    identifier: str
    entity_type: Optional[str] = None
    entity_uid: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.namespace.strip() or not self.identifier.strip():
            raise ValidationError("entity references require namespace and identifier")
        if self.entity_type is not None:
            if not self.entity_type.strip():
                raise ValidationError("entity_type must be non-empty when supplied")
            expected=make_entity_uid(self.namespace,self.entity_type,self.identifier)
            if self.entity_uid is None:
                object.__setattr__(self,"entity_uid",expected)
            elif self.entity_uid!=expected:
                raise ValidationError("entity_uid does not match canonical graph identity")


@dataclass(frozen=True)
class SourceObject:
    source_namespace: str
    upstream_object_type: str
    stable_upstream_id: str
    policy: PolicyLabels
    schema_version: str = "source-object/1"
    object_uid: Optional[str] = None

    def __post_init__(self) -> None:
        if not all(v.strip() for v in (self.source_namespace, self.upstream_object_type, self.stable_upstream_id)):
            raise ValidationError("source object identity fields must be non-empty")
        expected = make_object_uid(self.source_namespace, self.upstream_object_type, self.stable_upstream_id)
        if self.object_uid is None:
            object.__setattr__(self, "object_uid", expected)
        elif self.object_uid != expected:
            raise ValidationError("object_uid does not match canonical identity")


@dataclass(frozen=True)
class RetrievalObservation:
    observation_id: str
    retrieved_at: datetime
    connector_fingerprint: ComponentFingerprint
    request_fingerprint: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise ValidationError("observation_id must be non-empty")
        ensure_utc(self.retrieved_at)


@dataclass(frozen=True)
class ObservedRevision:
    object_uid: str
    raw_digest: str
    identity_attributes: Tuple[IdentityAttribute, ...]
    temporal: TemporalMetadata
    upstream_version: Optional[str] = None
    observations: Tuple[RetrievalObservation, ...] = ()
    schema_version: str = "observed-revision/1"
    revision_uid: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.object_uid.strip() or not self.raw_digest.strip():
            raise ValidationError("revision object_uid and raw_digest must be non-empty")
        attrs = tuple((item.name, item.value) for item in self.identity_attributes)
        expected = make_revision_uid(self.object_uid, self.upstream_version, self.raw_digest, attrs)
        if self.revision_uid is None:
            object.__setattr__(self, "revision_uid", expected)
        elif self.revision_uid != expected:
            raise ValidationError("revision_uid does not match canonical identity")

    def with_observation(self, observation: RetrievalObservation) -> "ObservedRevision":
        if any(item.observation_id == observation.observation_id for item in self.observations):
            return self
        return replace(self, observations=self.observations + (observation,))


@dataclass(frozen=True)
class NormalizedArtifact:
    revision_uid: str
    artifact_type: ArtifactType
    normalized_digest: str
    parser: ComponentFingerprint
    normalizer: ComponentFingerprint
    content_schema_version: str
    lineage: Lineage = Lineage()
    schema_version: str = "normalized-artifact/1"
    artifact_uid: Optional[str] = None

    def __post_init__(self) -> None:
        expected = make_artifact_uid(
            self.revision_uid, self.parser, self.normalizer, self.content_schema_version, self.normalized_digest
        )
        if self.artifact_uid is None:
            object.__setattr__(self, "artifact_uid", expected)
        elif self.artifact_uid != expected:
            raise ValidationError("artifact_uid does not match canonical identity")


@dataclass(frozen=True)
class Passage:
    artifact_uid: str
    revision_uid: str
    locator: Locator
    text: str
    chunker: ComponentFingerprint
    epistemic: EpistemicMetadata
    schema_version: str = "passage/1"
    passage_uid: Optional[str] = None

    def __post_init__(self) -> None:
        digest = sha256_hex(self.text.encode("utf-8"))
        expected = make_passage_uid(self.artifact_uid, self.chunker, locator_to_data(self.locator), digest)
        if self.passage_uid is None:
            object.__setattr__(self, "passage_uid", expected)
        elif self.passage_uid != expected:
            raise ValidationError("passage_uid does not match canonical identity")

    @property
    def provenance(self) -> ProvenanceRef:
        return ProvenanceRef(revision_uid=self.revision_uid, locator=self.locator)


@dataclass(frozen=True)
class IndexedRepresentation:
    passage_uid: str
    kind: RepresentationKind
    model: Optional[ComponentFingerprint] = None
    tokenizer: Optional[ComponentFingerprint] = None
    analyzer: Optional[ComponentFingerprint] = None
    prefix: Optional[ComponentFingerprint] = None
    schema_version: str = "indexed-representation/1"
    representation_uid: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind == RepresentationKind.DENSE and self.model is None:
            raise ValidationError("dense representations require a model fingerprint")
        if self.kind == RepresentationKind.LEXICAL and self.analyzer is None:
            raise ValidationError("lexical representations require an analyzer fingerprint")
        expected = make_representation_uid(
            self.passage_uid,
            self.kind.value,
            model=self.model,
            tokenizer=self.tokenizer,
            analyzer=self.analyzer,
            prefix=self.prefix,
        )
        if self.representation_uid is None:
            object.__setattr__(self, "representation_uid", expected)
        elif self.representation_uid != expected:
            raise ValidationError("representation_uid does not match canonical identity")


@dataclass(frozen=True)
class AssertionQualifier:
    name: str
    value: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("assertion qualifier name must be non-empty")


@dataclass(frozen=True)
class SourceAssertion:
    revision_uid: str
    subject: EntityRef
    predicate: str
    object: EntityRef
    qualifiers: Tuple[AssertionQualifier, ...]
    support: Tuple[ProvenanceRef, ...]
    epistemic: EpistemicMetadata
    schema_version: str = "source-assertion/1"
    assertion_uid: Optional[str] = None
    source_id: Optional[str] = None
    policy: Optional[PolicyLabels] = None
    available_at: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    system_manifest_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.support:
            raise ValidationError("source assertions require at least one supporting locator")
        for value in (self.available_at,self.valid_from,self.valid_to):
            if value is not None:
                ensure_utc(value)
        if self.valid_from is not None and self.valid_to is not None and self.valid_to<=self.valid_from:
            raise ValidationError("assertion valid interval must be increasing")
        if any(ref.revision_uid != self.revision_uid for ref in self.support):
            raise ValidationError("source assertion support must point at the source revision")
        expected = make_assertion_uid(
            self.revision_uid,
            {
                "subject": (self.subject.namespace, self.subject.identifier, self.subject.entity_type),
                "object": (self.object.namespace, self.object.identifier, self.object.entity_type),
            },
            self.predicate,
            tuple((item.name, item.value) for item in self.qualifiers),
            tuple(locator_to_data(ref.locator) for ref in self.support),
        )
        if self.assertion_uid is None:
            object.__setattr__(self, "assertion_uid", expected)
        elif self.assertion_uid != expected:
            raise ValidationError("assertion_uid does not match canonical identity")
