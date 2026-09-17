"""Deterministic CTI query planning and explicit answer-target projection."""
from __future__ import annotations

import re
from typing import Iterable, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from packages.evidence.domain import GraphPattern
from packages.evidence.schema import EvidenceModel, ExternalIdentifier
from packages.evidence.validation import require_sha256
from packages.retrieval.candidate import (
    ChunkCandidate,
    ObjectCandidate,
    PathCandidate,
    TargetObjectRef,
    TargetProjection,
)

Task = Literal["entity_lookup", "mapping", "report", "synthesis", "general", "unsupported"]
Language = Literal["en", "zh", "mixed", "unknown"]


class PlannerError(ValueError):
    pass


class PlannerBounds(EvidenceModel):
    top_k: int = Field(default=12, ge=1, le=50)
    max_graph_hops: int = Field(default=2, ge=0, le=3)
    max_seeds: int = Field(default=8, ge=1, le=8)
    neighbor_limit: int = Field(default=30, ge=1, le=30)
    path_limit: int = Field(default=40, ge=1, le=40)
    max_visited_nodes: int = Field(default=1000, ge=1, le=1000)


class QueryPlan(EvidenceModel):
    original_query: str = Field(min_length=1, max_length=8192)
    normalized_query: str = Field(min_length=1, max_length=8192)
    language: Language
    task: Task
    exact_keys: tuple[str, ...] = ()
    authorized_seed_ids: tuple[str, ...] = ()
    alias_candidate_ids: tuple[str, ...] = ()
    requested_target_types: tuple[str, ...] = ()
    pattern_ids: tuple[str, ...] = ()
    exact_enabled: bool = True
    lexical_enabled: bool = True
    dense_enabled: bool = True
    graph_enabled: bool = False
    bounds: PlannerBounds = Field(default_factory=PlannerBounds)
    unsupported_reason: str | None = None

    @field_validator("authorized_seed_ids", "alias_candidate_ids")
    @classmethod
    def validate_trusted_ids(cls, values: tuple[str, ...], info):
        for value in values:
            require_sha256(value, field_name=info.field_name)
        return values

    @model_validator(mode="after")
    def status_shape(self):
        if self.task == "unsupported" and not self.unsupported_reason:
            raise ValueError("unsupported task requires a reason")
        if self.task != "unsupported" and self.unsupported_reason:
            raise ValueError("unsupported_reason is only valid for unsupported tasks")
        if len(self.authorized_seed_ids) > self.bounds.max_seeds:
            raise ValueError("authorized_seed_ids exceed seed budget")
        return self


class PlannerDomainAdapter(Protocol):
    domain: str
    def parse_identifiers(self, query: str) -> list[ExternalIdentifier]: ...
    def allowed_graph_patterns(self, task_hint: str | None) -> list[GraphPattern]: ...


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_THREE_HOP_RE = re.compile(r"(?:\b3\s*[- ]?hop\b|\bthree\s*[- ]?hop\b|三跳)", re.IGNORECASE)


def detect_language(text: str) -> Language:
    has_cjk = bool(_CJK_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "zh"
    if has_latin:
        return "en"
    return "unknown"


def normalize_query(text: str) -> str:
    return " ".join(text.strip().split())


def exact_key(identifier: ExternalIdentifier) -> str:
    return f"{identifier.namespace}:{identifier.value}"


def _adapter_task(adapter: PlannerDomainAdapter, query: str, identifiers: list[ExternalIdentifier]) -> Task:
    method = getattr(adapter, "infer_task_hint", None)
    if method is not None:
        value = str(method(query, identifiers))
        if value not in {"entity_lookup", "mapping", "report", "synthesis", "general", "unsupported"}:
            raise PlannerError(f"domain adapter returned unsupported task hint: {value}")
        return value  # type: ignore[return-value]
    return "entity_lookup" if identifiers else "general"


def _adapter_target_types(adapter: PlannerDomainAdapter, query: str, identifiers: list[ExternalIdentifier], task: Task) -> tuple[str, ...]:
    method = getattr(adapter, "requested_target_types", None)
    if method is None:
        return ()
    return tuple(dict.fromkeys(str(value) for value in method(query, identifiers, task)))


def _select_patterns(adapter: PlannerDomainAdapter, *, task: Task, query: str, requested_hops: int) -> tuple[GraphPattern, ...]:
    if task != "mapping":
        return tuple(adapter.allowed_graph_patterns("general")) if requested_hops > 0 else ()
    explicit_three = bool(_THREE_HOP_RE.search(query))
    hint = "three_hop_mapping" if explicit_three else "mapping"
    patterns = tuple(adapter.allowed_graph_patterns(hint))
    if explicit_three and not any(pattern.max_hops >= 3 for pattern in patterns):
        raise PlannerError("three-hop request has no reviewed three-hop template")
    return patterns


class DeterministicQueryPlanner:
    """Model-free planner. Principal, corpus, scope and policy are trusted inputs elsewhere."""

    def __init__(self, adapter: PlannerDomainAdapter) -> None:
        self.adapter = adapter

    def plan(
        self,
        query: str,
        *,
        authorized_seed_ids: Iterable[str] = (),
        alias_candidate_ids: Iterable[str] = (),
        max_graph_hops: int = 2,
        top_k: int = 12,
        lexical_enabled: bool = True,
        dense_enabled: bool = True,
    ) -> QueryPlan:
        normalized = normalize_query(query)
        if not normalized:
            raise PlannerError("query must not be empty")
        bounds = PlannerBounds(top_k=top_k, max_graph_hops=max_graph_hops)
        identifiers = self.adapter.parse_identifiers(normalized)
        task = _adapter_task(self.adapter, normalized, identifiers)
        seeds = tuple(dict.fromkeys(authorized_seed_ids))[: bounds.max_seeds]
        aliases = tuple(dict.fromkeys(alias_candidate_ids))[: bounds.max_seeds]
        patterns = _select_patterns(self.adapter, task=task, query=normalized, requested_hops=max_graph_hops)
        requested_targets = _adapter_target_types(self.adapter, normalized, identifiers, task)
        explicit_three = bool(_THREE_HOP_RE.search(normalized))
        if task == "mapping":
            reviewed_cap = max((pattern.max_hops for pattern in patterns), default=max_graph_hops)
        else:
            reviewed_cap = 3 if explicit_three else 2
        effective_hops = min(max_graph_hops, reviewed_cap)
        bounds = bounds.model_copy(update={"max_graph_hops": effective_hops})

        pure_lookup = task == "entity_lookup"
        graph_enabled = task == "mapping" and bool(seeds) and bool(patterns) and effective_hops > 0
        return QueryPlan(
            original_query=query,
            normalized_query=normalized,
            language=detect_language(normalized),
            task=task,
            exact_keys=tuple(dict.fromkeys(exact_key(item) for item in identifiers)),
            authorized_seed_ids=seeds,
            alias_candidate_ids=aliases,
            requested_target_types=requested_targets,
            pattern_ids=tuple(pattern.pattern_id for pattern in patterns) if graph_enabled else (),
            exact_enabled=bool(identifiers),
            lexical_enabled=False if pure_lookup else lexical_enabled,
            dense_enabled=False if pure_lookup else dense_enabled,
            graph_enabled=graph_enabled,
            bounds=bounds,
        )


def project_candidate_targets(
    candidate: ObjectCandidate | ChunkCandidate | PathCandidate,
    *,
    task: Task,
    requested_target_types: tuple[str, ...],
    object_type_by_uid: dict[str, str],
    object_revision_by_uid: dict[str, str] | None = None,
    path_terminal_by_id: dict[str, str] | None = None,
    source_seed_ids: frozenset[str] = frozenset(),
) -> TargetProjection:
    object_revision_by_uid = object_revision_by_uid or {}
    path_terminal_by_id = path_terminal_by_id or {}
    if isinstance(candidate, ObjectCandidate):
        object_uid = candidate.object_uid
        kind = "direct_object"
    elif isinstance(candidate, ChunkCandidate):
        object_uid = candidate.object_uid
        kind = "chunk_parent"
    elif isinstance(candidate, PathCandidate):
        object_uid = path_terminal_by_id.get(candidate.path_id)
        if object_uid is None:
            raise PlannerError("path target projection requires an explicit terminal object")
        kind = "path_terminal"
    else:
        raise TypeError(type(candidate))

    object_type = object_type_by_uid.get(object_uid)
    include = True
    if task == "mapping":
        if object_uid in source_seed_ids:
            include = False
        if requested_target_types and object_type not in requested_target_types:
            include = False
    targets = ()
    if include:
        targets = (
            TargetObjectRef(
                object_uid=object_uid,
                object_revision_uid=object_revision_by_uid.get(object_uid),
                object_type=object_type,
            ),
        )
    return TargetProjection(
        candidate_id=candidate.candidate_id,
        evidence_kind=candidate.kind,
        targets=targets,
        projection_kind=kind,
    )


def deduplicate_target_objects(projections: Iterable[TargetProjection]) -> tuple[TargetObjectRef, ...]:
    """Deduplicate answer objects by first occurrence without asserting equivalence."""
    seen: set[str] = set()
    ordered: list[TargetObjectRef] = []
    for projection in projections:
        for target in projection.targets:
            if target.object_uid in seen:
                continue
            seen.add(target.object_uid)
            ordered.append(target)
    return tuple(ordered)


__all__ = [
    "DeterministicQueryPlanner",
    "PlannerBounds",
    "PlannerError",
    "QueryPlan",
    "TargetProjection",
    "deduplicate_target_objects",
    "detect_language",
    "project_candidate_targets",
]
