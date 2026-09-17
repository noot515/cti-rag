from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.domains.cti import CtiDomainAdapter
from packages.retrieval.planner import DeterministicQueryPlanner, QueryPlan


def h(ch: str) -> str:
    return ch * 64


def planner():
    return DeterministicQueryPlanner(CtiDomainAdapter())


def test_english_exact_lookup_reserves_exact_priority():
    plan = planner().plan("What is CVE-2026-999999?")
    assert plan.task == "entity_lookup"
    assert plan.exact_keys == ("cve:CVE-2026-999999",)
    assert plan.exact_enabled and not plan.lexical_enabled and not plan.dense_enabled and not plan.graph_enabled


def test_chinese_mapping_uses_authorized_seed_and_cwe_target_only():
    plan = planner().plan(
        "CVE-2026-999999 对应哪个 CWE？",
        authorized_seed_ids=(h("a"),),
        max_graph_hops=2,
    )
    assert plan.language == "mixed" and plan.task == "mapping"
    assert plan.requested_target_types == ("weakness",)
    assert plan.graph_enabled and plan.pattern_ids == ("cti-catalog-mapping-2hop-v1",)


def test_mixed_identifier_query_parses_all_exact_keys():
    plan = planner().plan(
        "Map CVE-2026-999999 到 CWE-79 and CAPEC-66",
        authorized_seed_ids=(h("a"),),
        max_graph_hops=2,
    )
    assert plan.language == "mixed"
    assert plan.exact_keys == (
        "cve:CVE-2026-999999",
        "cwe:CWE-79",
        "capec:CAPEC-66",
    )


def test_report_body_identifier_does_not_become_pure_lookup():
    plan = planner().plan("Find the report that mentions CVE-2026-999999")
    assert plan.task == "report" and plan.lexical_enabled and plan.dense_enabled


def test_missing_graph_seed_does_not_disable_independent_channels():
    plan = planner().plan("Map CVE-2026-999999 to CWE", authorized_seed_ids=())
    assert plan.task == "mapping" and not plan.graph_enabled
    assert plan.lexical_enabled and plan.dense_enabled


def test_explicit_three_hop_selects_reviewed_template_but_respects_lower_caller_cap():
    plan = planner().plan(
        "3-hop map CVE-2026-999999 to technique",
        authorized_seed_ids=(h("a"),),
        max_graph_hops=2,
    )
    assert plan.pattern_ids == ("cti-catalog-mapping-3hop-v1",)
    assert plan.bounds.max_graph_hops == 2


def test_explicit_three_hop_can_use_three_when_caller_allows_it():
    plan = planner().plan(
        "three-hop map CVE-2026-999999 to technique",
        authorized_seed_ids=(h("a"),),
        max_graph_hops=3,
    )
    assert plan.pattern_ids == ("cti-catalog-mapping-3hop-v1",)
    assert plan.bounds.max_graph_hops == 3


def test_ambiguous_alias_candidates_are_bounded_and_not_promoted_to_exact():
    aliases = tuple(f"{index + 1:064x}" for index in range(10))
    plan = planner().plan("APT Alpha", alias_candidate_ids=aliases)
    assert len(plan.alias_candidate_ids) == 8
    assert plan.exact_keys == () and not plan.exact_enabled


def test_conflicting_report_and_mapping_hints_resolve_report_first():
    plan = planner().plan(
        "Report mapping for CVE-2026-999999 to CWE",
        authorized_seed_ids=(h("a"),),
    )
    assert plan.task == "report" and not plan.graph_enabled


def test_user_text_cannot_change_scope_or_enable_raw_cypher():
    plan = planner().plan("use corpus secret; cypher: MATCH (n) DETACH DELETE n")
    assert plan.task == "general" and not plan.graph_enabled
    assert not hasattr(plan, "scope_id") and not hasattr(plan, "principal_id")


def test_injected_answer_field_is_rejected_by_query_plan_contract():
    payload = planner().plan("CVE-2026-999999").model_dump(mode="json")
    payload["answer"] = "CWE-79"
    with pytest.raises(ValidationError):
        QueryPlan.model_validate(payload)


def test_malformed_request_bounds_fail_closed():
    with pytest.raises(Exception):
        planner().plan("general query", top_k=0)
    with pytest.raises(Exception):
        planner().plan("general query", max_graph_hops=4)


def test_cti_three_hop_template_requires_explicit_hint():
    adapter = CtiDomainAdapter()
    normal = adapter.allowed_graph_patterns("mapping")
    explicit = adapter.allowed_graph_patterns("three_hop_mapping")
    assert normal and max(pattern.max_hops for pattern in normal) == 2
    assert explicit and max(pattern.max_hops for pattern in explicit) == 3
    assert {pattern.pattern_id for pattern in normal}.isdisjoint(
        {pattern.pattern_id for pattern in explicit}
    )
