"""Minimal boundary that keeps domain semantics out of generic retrieval mechanics."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import Field

from packages.evidence.schema import EvidenceModel, EvidenceObject, EvidenceRelation, ExternalIdentifier


class GraphPattern(EvidenceModel):
    pattern_id: str = Field(min_length=1)
    relation_sequence: tuple[str, ...]
    max_hops: int = Field(ge=0, le=3)
    source_types: tuple[str, ...] = ()
    target_types: tuple[str, ...] = ()


class NormalizedEvidenceBatch(EvidenceModel):
    domain: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    source_snapshot_id: str = Field(min_length=1)
    objects: tuple[EvidenceObject, ...] = ()
    relations: tuple[EvidenceRelation, ...] = ()


class DomainAdapter(Protocol):
    domain: str

    def normalize(self, source_record: Any) -> NormalizedEvidenceBatch: ...

    def parse_identifiers(self, query: str) -> list[ExternalIdentifier]: ...

    def exact_lookup_keys(self, evidence_object: EvidenceObject) -> list[str]: ...

    def allowed_graph_patterns(self, task_hint: str | None) -> list[GraphPattern]: ...
