from __future__ import annotations

import pytest

from benchmark.advanced.ablations import AblationSpec, native_ablation_matrix, validate_fair_matrix
from benchmark.advanced.splits import QueryGrouping, assert_no_group_leakage, grouped_split


def test_ablation_matrix_is_complete_and_budget_fair():
    specs = native_ablation_matrix(top_k=12, pre_rerank_limit=60, context_budget=8000)
    validate_fair_matrix(specs)
    assert [spec.name for spec in specs] == [
        "R1",
        "R2",
        "R3",
        "R4",
        "R5",
        "R6",
        "C1-basic",
        "C1-structured",
    ]
    assert {spec.top_k for spec in specs} == {12}
    assert {spec.pre_rerank_limit for spec in specs} == {60}
    assert {spec.context_budget for spec in specs} == {8000}
    assert all(spec.authorization_enabled for spec in specs)


def test_authorization_cannot_be_ablated():
    invalid = (
        AblationSpec("R1", "dense only", False, False, True, False, False, authorization_enabled=False),
    )
    with pytest.raises(ValueError, match="authorization"):
        validate_fair_matrix(invalid)


def test_c1_requires_equivalent_budget():
    specs = list(native_ablation_matrix())
    index = next(i for i, spec in enumerate(specs) if spec.name == "C1-basic")
    specs[index] = AblationSpec(
        **{
            **specs[index].as_dict(),
            "context_budget": 4000,
        }
    )
    with pytest.raises(ValueError, match="budgets|equivalent"):
        validate_fair_matrix(specs)


def test_grouped_split_is_deterministic_and_blocks_both_leakage_axes():
    rows = (
        QueryGrouping("q1", "object-a", "family-1"),
        QueryGrouping("q2", "object-a", "family-2"),
        # q2 and q3 connect transitively through family-2, so all q1-q3 must stay together.
        QueryGrouping("q3", "object-b", "family-2"),
        QueryGrouping("q4", "object-c", "family-3"),
        QueryGrouping("q5", "object-d", "family-4"),
    )
    first = grouped_split(rows, seed=7, dev_fraction=0.5)
    second = grouped_split(rows, seed=7, dev_fraction=0.5)
    assert first == second
    assert first.grouping_sha256
    assert first.split_sha256
    assert_no_group_leakage(first, rows)

    dev = set(first.dev_query_ids)
    test = set(first.test_query_ids)
    linked = {"q1", "q2", "q3"}
    assert linked <= dev or linked <= test


def test_split_rejects_grouping_that_cannot_create_nonempty_dev_and_test():
    rows = (
        QueryGrouping("q1", "same", "same-family"),
        QueryGrouping("q2", "same", "same-family"),
    )
    with pytest.raises(ValueError, match="nonempty"):
        grouped_split(rows)
