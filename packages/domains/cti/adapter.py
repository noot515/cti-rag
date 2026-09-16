"""Concrete CTI domain adapter for P01 contracts and synthetic fixtures."""

from __future__ import annotations

from typing import Any

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

    def allowed_graph_patterns(self, task_hint: str | None) -> list[GraphPattern]:
        return allowed_graph_patterns(task_hint)
