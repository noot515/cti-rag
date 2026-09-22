"""Typed retrieval candidates that preserve non-text payloads."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Tuple, Union

from .errors import UnknownDiscriminatorError, ValidationError
from .provenance import ProvenanceRef, locator_from_dict


class ScoreDirection(str, Enum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    UNORDERED = "unordered"


@dataclass(frozen=True)
class ScoreMetadata:
    channel: str
    value: Optional[float] = None
    direction: ScoreDirection = ScoreDirection.HIGHER_IS_BETTER
    raw_rank: Optional[int] = None
    backend: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.channel.strip():
            raise ValidationError("score channel must be non-empty")
        if self.raw_rank is not None and self.raw_rank < 1:
            raise ValidationError("raw_rank is 1-based")


@dataclass(frozen=True)
class PassageHit:
    hit_id: str
    passage_uid: str
    revision_uid: str
    provenance: ProvenanceRef
    text: str
    scores: Tuple[ScoreMetadata, ...] = ()
    kind: str = "passage"

    def __post_init__(self) -> None:
        if not self.hit_id.strip() or not self.passage_uid.strip() or not self.revision_uid.strip():
            raise ValidationError("passage hit identifiers must be non-empty")
        if self.provenance.revision_uid != self.revision_uid:
            raise ValidationError("passage provenance revision must match revision_uid")

    @property
    def citation_key(self) -> Tuple[str, str]:
        return (self.revision_uid, repr(self.provenance.locator))


@dataclass(frozen=True)
class EntityHit:
    hit_id: str
    entity_uid: str
    revision_uid: str
    provenance: ProvenanceRef
    entity_type: str
    label: str
    attributes: Tuple[Tuple[str, str], ...] = ()
    scores: Tuple[ScoreMetadata, ...] = ()
    kind: str = "entity"

    def __post_init__(self) -> None:
        if not all(x.strip() for x in (self.hit_id, self.entity_uid, self.revision_uid, self.entity_type, self.label)):
            raise ValidationError("entity hit fields must be non-empty")
        if self.provenance.revision_uid != self.revision_uid:
            raise ValidationError("entity provenance revision must match revision_uid")

    @property
    def citation_key(self) -> Tuple[str, str]:
        return (self.revision_uid, repr(self.provenance.locator))


@dataclass(frozen=True)
class GraphPathHit:
    hit_id: str
    path_uid: str
    revision_uids: Tuple[str, ...]
    assertions: Tuple[str, ...]
    provenances: Tuple[ProvenanceRef, ...]
    scores: Tuple[ScoreMetadata, ...] = ()
    kind: str = "graph_path"

    def __post_init__(self) -> None:
        if not self.hit_id.strip() or not self.path_uid.strip():
            raise ValidationError("graph path identifiers must be non-empty")
        if not self.assertions or not self.provenances:
            raise ValidationError("graph paths require assertions and provenance")
        allowed = set(self.revision_uids)
        if any(ref.revision_uid not in allowed for ref in self.provenances):
            raise ValidationError("graph provenance must refer to one of path revision_uids")

    @property
    def citation_key(self) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        return (self.revision_uids, self.assertions)


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    REJECTED = "rejected"


@dataclass(frozen=True)
class StructuredField:
    name: str
    value: Any
    data_type: str
    unit: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.data_type.strip():
            raise ValidationError("structured field name and data_type must be non-empty")


@dataclass(frozen=True)
class StructuredResult:
    hit_id: str
    result_uid: str
    revision_uids: Tuple[str, ...]
    fields: Tuple[StructuredField, ...]
    provenances: Tuple[ProvenanceRef, ...]
    verification_status: VerificationStatus
    calculation_fingerprint: Optional[str] = None
    scores: Tuple[ScoreMetadata, ...] = ()
    kind: str = "structured"

    def __post_init__(self) -> None:
        if not self.hit_id.strip() or not self.result_uid.strip() or not self.fields:
            raise ValidationError("structured result requires identifiers and at least one field")
        allowed = set(self.revision_uids)
        if any(ref.revision_uid not in allowed for ref in self.provenances):
            raise ValidationError("structured provenance must refer to a result revision")
        if self.verification_status == VerificationStatus.VERIFIED and not self.calculation_fingerprint:
            raise ValidationError("verified structured results require a calculation fingerprint")

    @property
    def citation_key(self) -> Tuple[str, Tuple[str, ...]]:
        return (self.result_uid, self.revision_uids)


Candidate = Union[PassageHit, EntityHit, GraphPathHit, StructuredResult]


def _score_from_dict(data: Mapping[str, Any]) -> ScoreMetadata:
    try:
        direction = ScoreDirection(data.get("direction", ScoreDirection.HIGHER_IS_BETTER.value))
    except ValueError as exc:
        raise UnknownDiscriminatorError(f"unknown score direction: {data.get('direction')!r}") from exc
    value = data.get("value")
    return ScoreMetadata(
        channel=str(data["channel"]),
        value=None if value is None else float(value),
        direction=direction,
        raw_rank=None if data.get("raw_rank") is None else int(data["raw_rank"]),
        backend=None if data.get("backend") is None else str(data["backend"]),
    )


def _provenance_from_dict(data: Mapping[str, Any]) -> ProvenanceRef:
    return ProvenanceRef(
        revision_uid=str(data["revision_uid"]),
        locator=locator_from_dict(data["locator"]),
        source_uri=None if data.get("source_uri") is None else str(data["source_uri"]),
    )


def candidate_from_dict(data: Mapping[str, Any]) -> Candidate:
    kind = data.get("kind")
    scores = tuple(_score_from_dict(item) for item in data.get("scores", ()))
    if kind == "passage":
        return PassageHit(
            hit_id=str(data["hit_id"]), passage_uid=str(data["passage_uid"]), revision_uid=str(data["revision_uid"]),
            provenance=_provenance_from_dict(data["provenance"]), text=str(data["text"]), scores=scores,
        )
    if kind == "entity":
        return EntityHit(
            hit_id=str(data["hit_id"]), entity_uid=str(data["entity_uid"]), revision_uid=str(data["revision_uid"]),
            provenance=_provenance_from_dict(data["provenance"]), entity_type=str(data["entity_type"]),
            label=str(data["label"]), attributes=tuple((str(k), str(v)) for k, v in data.get("attributes", ())), scores=scores,
        )
    if kind == "graph_path":
        return GraphPathHit(
            hit_id=str(data["hit_id"]), path_uid=str(data["path_uid"]),
            revision_uids=tuple(str(v) for v in data.get("revision_uids", ())),
            assertions=tuple(str(v) for v in data.get("assertions", ())),
            provenances=tuple(_provenance_from_dict(v) for v in data.get("provenances", ())), scores=scores,
        )
    if kind == "structured":
        try:
            status = VerificationStatus(data["verification_status"])
        except ValueError as exc:
            raise UnknownDiscriminatorError(f"unknown verification status: {data.get('verification_status')!r}") from exc
        return StructuredResult(
            hit_id=str(data["hit_id"]), result_uid=str(data["result_uid"]),
            revision_uids=tuple(str(v) for v in data.get("revision_uids", ())),
            fields=tuple(StructuredField(**item) for item in data.get("fields", ())),
            provenances=tuple(_provenance_from_dict(v) for v in data.get("provenances", ())),
            verification_status=status, calculation_fingerprint=data.get("calculation_fingerprint"), scores=scores,
        )
    raise UnknownDiscriminatorError(f"unknown candidate kind: {kind!r}")


def merge_candidates(groups: Sequence[Sequence[Candidate]]) -> Tuple[Candidate, ...]:
    """Deduplicate retrieval attempts without collapsing distinct source revisions.

    The merge key is the citable identity of each typed payload, never text alone.
    This intentionally keeps identical passages from different archives, editions,
    or revisions as separate candidates.
    """

    merged = []
    seen = set()
    for group in groups:
        for candidate in group:
            key = (candidate.kind, candidate.citation_key)
            if key not in seen:
                seen.add(key)
                merged.append(candidate)
    return tuple(merged)
