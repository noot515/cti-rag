"""Typed CTI extensions over the generic evidence contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from packages.domains.base import NormalizedEvidenceBatch
from packages.evidence.schema import EvidenceChunk, EvidenceObject, EvidenceRelation, EvidenceModel
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


class CtiOtherData(EvidenceModel):
    family: Literal["other"] = "other"
    source_type: str = Field(min_length=1)


CtiFamilyData = Annotated[
    CtiVulnerabilityData
    | CtiWeaknessData
    | CtiAttackPatternData
    | CtiReportData
    | CtiOtherData,
    Field(discriminator="family"),
]


class CtiObject(EvidenceObject):
    domain: Literal["cti"] = "cti"
    extension_type: Literal["cti"] = "cti"
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
    def stix_id_is_preserved_and_valid(cls, value: str | None) -> str | None:
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


class CtiNormalizedEvidenceBatch(NormalizedEvidenceBatch):
    domain: Literal["cti"] = "cti"
    objects: tuple[CtiObject, ...] = ()
    relations: tuple[CtiRelationship, ...] = ()
