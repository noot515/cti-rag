from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.domains.cti import CtiDomainAdapter
from packages.domains.cti.identifiers import parse_cti_identifiers
from packages.domains.cti.markings import CtiMarking, GranularMarking, TlpLabel, to_policy_metadata
from packages.domains.cti.schema import CtiObject, CtiRelationship
from packages.evidence.ids import object_uid

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "cti" / "public_fixture.json"


def _manifest():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_cti_fixture_normalizes_to_typed_objects_and_relationships():
    adapter = CtiDomainAdapter()
    batch = adapter.normalize(_manifest())
    assert batch.domain == "cti"
    assert batch.scope_id == "public-fixture"
    assert len(batch.objects) == 5
    assert len(batch.relations) == 4
    assert all(isinstance(obj, CtiObject) for obj in batch.objects)
    assert all(isinstance(rel, CtiRelationship) for rel in batch.relations)
    assert batch.model_validate_json(batch.model_dump_json()) == batch


def test_synthetic_fixture_contains_three_hop_mapping_chain_and_distractor():
    batch = CtiDomainAdapter().normalize(_manifest())
    ids = {
        identifier.value
        for obj in batch.objects
        for identifier in obj.external_ids
    }
    assert {"CVE-2026-999999", "CWE-79", "CAPEC-66", "T1059.001", "T9999"} <= ids
    assert sum(rel.normalized_relation == "maps_to" for rel in batch.relations) == 4


def test_same_endpoint_relationships_remain_distinct_and_independently_citable():
    batch = CtiDomainAdapter().normalize(_manifest())
    cwe = next(obj for obj in batch.objects if any(i.value == "CWE-79" for i in obj.external_ids))
    capec = next(obj for obj in batch.objects if any(i.value == "CAPEC-66" for i in obj.external_ids))
    matching = [
        rel
        for rel in batch.relations
        if rel.source_object_uid == cwe.uid and rel.target_object_uid == capec.uid
    ]
    assert len(matching) == 2
    assert matching[0].uid != matching[1].uid
    assert matching[0].revision_uid != matching[1].revision_uid
    assert matching[0].source_evidence_locator != matching[1].source_evidence_locator
    assert matching[0].evidence_refs and matching[1].evidence_refs


def test_identifier_parser_preserves_whole_cti_identifiers_without_alias_guessing():
    found = parse_cti_identifiers(
        "Map CVE-2026-999999 through CWE-79 and CAPEC-66 to T1059.001; ignore name-only guesses."
    )
    assert [(item.namespace, item.value) for item in found] == [
        ("cve", "CVE-2026-999999"),
        ("cwe", "CWE-79"),
        ("capec", "CAPEC-66"),
        ("attack", "T1059.001"),
    ]


def test_exact_lookup_keys_are_domain_owned_and_source_preserving():
    adapter = CtiDomainAdapter()
    batch = adapter.normalize(_manifest())
    cve = next(obj for obj in batch.objects if any(i.value == "CVE-2026-999999" for i in obj.external_ids))
    keys = adapter.exact_lookup_keys(cve)
    assert "cve:CVE-2026-999999" in keys
    assert "source:fixture-public:fixture-cve-2026-999999" in keys


def test_domain_adapter_does_not_expose_authorization_method():
    adapter = CtiDomainAdapter()
    assert not hasattr(adapter, "authorize_evidence")
    assert not hasattr(adapter, "resolve_scope")


def test_reviewed_graph_patterns_are_bounded_and_not_user_generated():
    adapter = CtiDomainAdapter()

    mapping = adapter.allowed_graph_patterns("mapping")
    assert len(mapping) == 1
    assert mapping[0].pattern_id == "cti-catalog-mapping-2hop-v1"
    assert mapping[0].max_hops == 2
    assert mapping[0].relation_sequence == ("maps_to",)

    explicit_three_hop = adapter.allowed_graph_patterns("three_hop_mapping")
    assert len(explicit_three_hop) == 1
    assert explicit_three_hop[0].pattern_id == "cti-catalog-mapping-3hop-v1"
    assert explicit_three_hop[0].max_hops == 3
    assert explicit_three_hop[0].relation_sequence == ("maps_to",)

    general = adapter.allowed_graph_patterns("something-else")
    assert all(pattern.max_hops <= 2 for pattern in general)


def test_marking_normalization_preserves_tlp_labels_without_numeric_clearance_order():
    amber_strict = CtiMarking(
        marking_ref="marking--amber-strict",
        definition_type="tlp",
        definition="AMBER+STRICT",
    )
    assert amber_strict.tlp_label() is TlpLabel.AMBER_STRICT
    policy = to_policy_metadata(
        source_instances=("fixture-public",),
        markings=(amber_strict,),
        granular_markings=(GranularMarking(marking_ref="marking--x", selectors=("description",)),),
    )
    assert policy.dissemination == ("tlp:amber+strict",)
    assert policy.granular_selectors == ("description",)


def test_unknown_marking_is_not_silently_treated_as_public():
    proprietary = CtiMarking(
        marking_ref="marking--custom",
        definition_type="statement",
        definition="internal only",
    )
    policy = to_policy_metadata(source_instances=("fixture-public",), markings=(proprietary,))
    assert policy.unresolved_markings is True


def test_identical_names_across_domains_do_not_merge_identity():
    cti = object_uid("cti", "fixture", "shared-record")
    other = object_uid("networking", "fixture", "shared-record")
    assert cti != other


def test_declared_marking_without_definition_is_unresolved_and_fail_closed_metadata():
    policy = to_policy_metadata(
        source_instances=("fixture-public",),
        declared_marking_refs=("marking--missing-definition",),
    )
    assert policy.marking_refs == ("marking--missing-definition",)
    assert policy.unresolved_markings is True


def test_report_object_refs_become_explicit_noncausal_reference_assertions():
    manifest = _manifest()
    manifest["objects"].append(
        {
            "source_object_id": "fixture-report-1",
            "object_type": "report",
            "name": "Synthetic report",
            "description": "Synthetic report references an object without asserting causality.",
            "external_ids": [],
            "family_data": {"object_refs": ["fixture-cve-2026-999999"]}
        }
    )
    batch = CtiDomainAdapter().normalize(manifest)
    report = next(obj for obj in batch.objects if obj.object_type == "report")
    cve = next(obj for obj in batch.objects if any(i.value == "CVE-2026-999999" for i in obj.external_ids))
    references = [
        relation
        for relation in batch.relations
        if relation.source_object_uid == report.uid and relation.target_object_uid == cve.uid
    ]
    assert len(references) == 1
    assert references[0].normalized_relation == "references"
    assert references[0].assertion_kind == "embedded_reference"
    assert references[0].source_evidence_locator == "object_refs[0]"
