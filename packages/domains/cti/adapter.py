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

    def infer_task_hint(self, query: str, identifiers: list[ExternalIdentifier]) -> str:
        folded = query.casefold()
        if any(term in folded for term in ("summarize", "summary", "synthesize", "overview")) or any(
            term in query for term in ("总结", "概述", "综合")
        ):
            return "synthesis"
        if "report" in folded or "报告" in query:
            return "report"
        mapping = any(
            term in folded
            for term in ("map", "mapping", "maps to", "mapped to", "weakness", "attack pattern", "technique")
        ) or any(term in query for term in ("对应", "映射", "弱点", "攻击模式", "技术"))
        if identifiers and mapping:
            return "mapping"
        return "entity_lookup" if identifiers else "general"

    def requested_target_types(
        self, query: str, identifiers: list[ExternalIdentifier], task_hint: str
    ) -> list[str]:
        folded = query.casefold()
        if task_hint == "mapping":
            for identifier in identifiers:
                folded = folded.replace(identifier.value.casefold(), " ")
        requested: list[str] = []
        if "cwe" in folded or "weakness" in folded or "弱点" in query:
            requested.append("weakness")
        if "capec" in folded or "attack pattern" in folded or "攻击模式" in query:
            requested.append("attack-pattern")
        if "technique" in folded or "技术" in query or "att&ck" in folded:
            requested.append("technique")
        if task_hint == "entity_lookup":
            namespace_types = {
                "cve": "vulnerability",
                "cwe": "weakness",
                "capec": "attack-pattern",
                "attack": "technique",
                "mitre-attack": "technique",
            }
            requested.extend(
                namespace_types[identifier.namespace.casefold()]
                for identifier in identifiers
                if identifier.namespace.casefold() in namespace_types
            )
        return list(dict.fromkeys(requested))

    def allowed_graph_patterns(self, task_hint: str | None) -> list[GraphPattern]:
        return allowed_graph_patterns(task_hint)

    def relation_templates(self, task_hint: str | None) -> list[GraphPattern]:
        return allowed_graph_patterns(task_hint)
