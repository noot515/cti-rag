"""Preregistered advanced retrieval/context ablation matrix."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable


@dataclass(frozen=True)
class AblationSpec:
    name: str
    description: str
    exact: bool
    lexical: bool
    dense: bool
    graph: bool
    reranker: bool
    context_mode: str = "structured"
    top_k: int = 12
    pre_rerank_limit: int = 60
    context_budget: int = 8000
    authorization_enabled: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def native_ablation_matrix(
    *,
    top_k: int = 12,
    pre_rerank_limit: int = 60,
    context_budget: int = 8000,
) -> tuple[AblationSpec, ...]:
    common = dict(
        top_k=top_k,
        pre_rerank_limit=pre_rerank_limit,
        context_budget=context_budget,
        authorization_enabled=True,
    )
    return (
        AblationSpec("R1", "dense only", False, False, True, False, False, **common),
        AblationSpec("R2", "lexical only", False, True, False, False, False, **common),
        AblationSpec("R3", "dense + lexical", False, True, True, False, False, **common),
        AblationSpec("R4", "R3 + exact", True, True, True, False, False, **common),
        AblationSpec("R5", "R4 + graph", True, True, True, True, False, **common),
        AblationSpec("R6", "R5 + single final reranker", True, True, True, True, True, **common),
        AblationSpec("C1-basic", "R6 with basic context formatting", True, True, True, True, True, context_mode="basic", **common),
        AblationSpec("C1-structured", "R6 with structured context formatting", True, True, True, True, True, context_mode="structured", **common),
    )


def validate_fair_matrix(specs: Iterable[AblationSpec]) -> None:
    specs = tuple(specs)
    if not specs:
        raise ValueError("ablation matrix is empty")
    for spec in specs:
        if not spec.authorization_enabled:
            raise ValueError("authorization may not be ablated")
    reference = (specs[0].top_k, specs[0].pre_rerank_limit, specs[0].context_budget)
    for spec in specs[1:]:
        observed = (spec.top_k, spec.pre_rerank_limit, spec.context_budget)
        if observed != reference:
            raise ValueError("ablation candidate/final/context budgets must remain fixed")

    by_name = {spec.name: spec for spec in specs}
    required = {"R1", "R2", "R3", "R4", "R5", "R6", "C1-basic", "C1-structured"}
    if set(by_name) != required:
        raise ValueError("ablation matrix must contain exactly R1-R6 and both C1 modes")
    if by_name["C1-basic"].context_budget != by_name["C1-structured"].context_budget:
        raise ValueError("C1 context modes must use equivalent context budgets")


def l0_comparator_metadata(*, canonical_mapping_available: bool) -> dict[str, object]:
    return {
        "name": "L0",
        "description": "legacy comparator",
        "canonical_object_mapping_available": canonical_mapping_available,
        "authorization_ablation": False,
    }


__all__ = ["AblationSpec", "l0_comparator_metadata", "native_ablation_matrix", "validate_fair_matrix"]
