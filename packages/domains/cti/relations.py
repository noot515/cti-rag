"""Reviewed CTI relation/assertion patterns; never user-generated traversal."""

from __future__ import annotations

from packages.domains.base import GraphPattern

_GENERAL_PATTERNS = (
    GraphPattern(
        pattern_id="cti-reviewed-general-v1",
        relation_sequence=("maps_to", "references", "affects", "uses"),
        max_hops=2,
    ),
)
_MAPPING_PATTERNS = (
    GraphPattern(
        pattern_id="cti-catalog-mapping-3hop-v1",
        relation_sequence=("maps_to",),
        max_hops=3,
        source_types=("vulnerability", "weakness", "attack-pattern"),
        target_types=("weakness", "attack-pattern", "technique"),
    ),
)
_ALLOWED_RELATIONS = frozenset({"maps_to", "references", "affects", "uses"})
_ALLOWED_ASSERTION_KINDS = frozenset(
    {"explicit", "extracted", "inferred", "catalog_mapping", "embedded_reference", "cross_source_equivalence"}
)


def normalize_relation(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    normalized = {
        "mapped_to": "maps_to",
        "mapping": "maps_to",
        "reference": "references",
        "object_ref": "references",
        "object_refs": "references",
    }.get(normalized, normalized)
    if normalized not in _ALLOWED_RELATIONS:
        raise ValueError(f"unreviewed CTI relation: {value}")
    return normalized


def normalize_assertion_kind(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in _ALLOWED_ASSERTION_KINDS:
        raise ValueError(f"unsupported CTI assertion kind: {value}")
    return normalized


def allowed_graph_patterns(task_hint: str | None) -> list[GraphPattern]:
    if task_hint and task_hint.strip().lower() in {"mapping", "catalog_mapping", "three_hop_mapping"}:
        return list(_MAPPING_PATTERNS)
    return list(_GENERAL_PATTERNS)
