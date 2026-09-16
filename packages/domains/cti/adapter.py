"""Concrete CTI domain adapter: pure normalization and reviewed retrieval hints."""

from __future__ import annotations

from typing import Any, Iterable

from packages.domains.base import GraphPattern, NormalizedEvidenceBatch
from packages.evidence.schema import EvidenceObject, ExternalIdentifier

from .identifiers import exact_identifier_key, parse_cti_identifiers
from .normalize import normalize_cti_fixture_manifest
from .relations import allowed_graph_patterns


class CtiDomainAdapter:
    domain = "cti"

    def normalize(self, source_record: Any) -> NormalizedEvidenceBatch:
        return normalize_cti_fixture_manifest(source_record)

    def parse_identifiers(self, query: str) -> list[ExternalIdentifier]:
        return parse_cti_identifiers(query)

    def exact_lookup_keys(self, evidence_object: EvidenceObject) -> list[str]:
        if evidence_object.domain != self.domain:
            raise ValueError("CTI adapter cannot derive lookup keys for another domain")
        keys = [exact_identifier_key(identifier) for identifier in evidence_object.external_ids]
        keys.extend(f"source:{ref.source_instance}:{ref.source_object_id}" for ref in evidence_object.source_refs)
        stix_id = getattr(evidence_object, "stix_id", None)
        if stix_id:
            keys.append(f"stix:{stix_id}")
        return list(dict.fromkeys(keys))

    def alias_candidates(self, alias: str, objects: Iterable[EvidenceObject]) -> list[EvidenceObject]:
        needle = alias.strip().casefold()
        if not needle:
            return []
        return [obj for obj in objects if any(candidate.casefold() == needle for candidate in obj.aliases)]

    def field_serialization_hints(self) -> dict[str, str]:
        return {
            "name": "title",
            "description": "body",
            "external_ids": "exact-identifiers",
            "aliases": "ambiguous-aliases",
            "family_data": "domain-structured",
            "markings": "policy-metadata",
        }

    def allowed_graph_patterns(self, task_hint: str | None) -> list[GraphPattern]:
        return allowed_graph_patterns(task_hint)

    def relation_templates(self, task_hint: str | None) -> list[GraphPattern]:
        return allowed_graph_patterns(task_hint)
