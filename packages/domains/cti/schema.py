"""Typed CTI extensions over generic evidence contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from packages.domains.base import NormalizedEvidenceBatch
from packages.evidence.schema import EvidenceChunk, EvidenceModel, EvidenceObject, EvidenceRelation

from .markings import CtiMarking, GranularMarking
from .validation import validate_stix_id


class CtiVulnerabilityData(EvidenceModel):
    family: Literal["vulnerability"] = "vulnerability"
    cve_id: str | None = None
    affected_products: tuple[str, ...] = ()


class CtiWeaknessData(EvidenceModel):
    family: Literal["weakness"] = "weakness"
    cwe_id: str | None = None


class CtiAttackPatternData(EvidenceModel):
    family: Literal["attack_pattern"] = "attack_pattern"
    capec_id: str | None = None
    attack_technique_id: str | None = None


class CtiReportData(EvidenceModel):
    family: Literal["report"] = "report"
    object_refs: tuple[str, ...] = ()


class CtiIndicatorData(EvidenceModel):
    family: Literal["indicator"] = "indicator"
    pattern: str | None = None
    pattern_type: str | None = None


class CtiOtherData(EvidenceModel):
    family: Literal["other"] = "other"
    source_type: str = Field(min_length=1)


CtiFamilyData = Annotated[
    CtiVulnerabilityData | CtiWeaknessData | CtiAttackPatternData | CtiReportData | CtiIndicatorData | CtiOtherData,
    Field(discriminator="family"),
]


class CtiObject(EvidenceObject):
    domain: Literal["cti"] = "cti"
    extension_type: Literal["cti"] = "cti"
    stix_family: Literal["sdo", "sco", "sro", "meta", "internal"] | None = None
    stix_type: str | None = None
    stix_id: str | None = None
    revoked: bool = False
    deprecated: bool = False
    deleted: bool = False
    confidence: int | None = Field(default=None, ge=0, le=100)
    marking_refs: tuple[str, ...] = ()
    markings: tuple[CtiMarking, ...] = ()
    granular_markings: tuple[GranularMarking, ...] = ()
    family_data: CtiFamilyData

    @field_validator("stix_id")
    @classmethod
    def validate_stix_identifier(cls, value: str | None) -> str | None:
        if value is not None:
            validate_stix_id(value)
        return value


class CtiRelationship(EvidenceRelation):
    domain: Literal["cti"] = "cti"
    extension_type: Literal["cti-relationship"] = "cti-relationship"
    relationship_kind: str = Field(min_length=1)
    source_evidence_locator: str | None = None
    marking_refs: tuple[str, ...] = ()
    markings: tuple[CtiMarking, ...] = ()
    granular_markings: tuple[GranularMarking, ...] = ()
    producer_confidence: int | None = Field(default=None, ge=0, le=100)


class CtiChunk(EvidenceChunk):
    domain: Literal["cti"] = "cti"
    extension_type: Literal["cti-chunk"] = "cti-chunk"
    effective_marking_refs: tuple[str, ...] = ()
    granular_selectors: tuple[str, ...] = ()
    citation_locator: str | None = None


class CtiQuarantinedRecord(EvidenceModel):
    record_kind: Literal["object", "relation", "reference"]
    source_record_id: str | None = None
    reason_code: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    raw_payload_sha256: str | None = None


class CtiNormalizedEvidenceBatch(NormalizedEvidenceBatch):
    domain: Literal["cti"] = "cti"
    objects: tuple[CtiObject, ...] = ()
    relations: tuple[CtiRelationship, ...] = ()
    chunks: tuple[CtiChunk, ...] = ()
    quarantined: tuple[CtiQuarantinedRecord, ...] = ()

    @property
    def assertions(self) -> tuple[CtiRelationship, ...]:
        return self.relations

    @property
    def quarantine_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.quarantined:
            counts[record.reason_code] = counts.get(record.reason_code, 0) + 1
        return counts
