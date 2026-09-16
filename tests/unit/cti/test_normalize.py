from __future__ import annotations

import json
from pathlib import Path

from packages.domains.cti import CtiDomainAdapter, load_cti_corpus_fixture
from packages.domains.cti.schema import CtiReportData
from packages.evidence.ids import object_uid

ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "cti"


def _legacy():
    return json.loads((ROOT / "public_fixture.json").read_text(encoding="utf-8"))


def test_fixture_normalization_is_deterministic_and_confidence_null_is_preserved():
    adapter = CtiDomainAdapter()
    first = adapter.normalize(_legacy())
    second = adapter.normalize(_legacy())
    assert first == second
    cve = next(obj for obj in first.objects if any(item.value == "CVE-2026-999999" for item in obj.external_ids))
    assert cve.confidence is None
    assert cve.description is not None
    assert not first.quarantined


def test_aliases_are_ambiguous_candidates_never_exact_identity():
    batch = load_cti_corpus_fixture(ROOT / "corpus.manifest.json")
    adapter = CtiDomainAdapter()
    matches = adapter.alias_candidates("Shared Synthetic Alias", batch.objects)
    assert len(matches) == 2
    assert all("Shared Synthetic Alias" not in adapter.exact_lookup_keys(obj) for obj in matches)


def test_report_object_refs_are_noncausal_reference_assertions():
    batch = load_cti_corpus_fixture(ROOT / "corpus.manifest.json")
    report = next(obj for obj in batch.objects if isinstance(obj.family_data, CtiReportData))
    cve = next(obj for obj in batch.objects if any(item.value == "CVE-2026-999999" for item in obj.external_ids))
    references = [
        relation
        for relation in batch.relations
        if relation.source_object_uid == report.uid and relation.target_object_uid == cve.uid
    ]
    assert len(references) == 1
    assert references[0].normalized_relation == "references"
    assert references[0].assertion_kind == "embedded_reference"
    assert references[0].source_evidence_locator == "object_refs[0]"


def test_missing_marking_definition_suppresses_object_with_quarantine_reason():
    manifest = _legacy()
    manifest["objects"][0]["marking_refs"] = ["missing"]
    batch = CtiDomainAdapter().normalize(manifest)
    assert all(obj.source_refs[0].source_object_id != "fixture-cve-2026-999999" for obj in batch.objects)
    assert batch.quarantine_counts["unresolved-marking"] == 1
    assert batch.quarantine_counts["dangling-relation-endpoint"] == 1


def test_unsupported_granular_selector_suppresses_whole_object():
    manifest = _legacy()
    manifest["marking_definitions"] = [{"marking_ref": "m-clear", "definition_type": "tlp", "definition": "CLEAR"}]
    manifest["objects"][0]["granular_markings"] = [
        {"marking_ref": "m-clear", "selectors": ["x_private.secret"]}
    ]
    batch = CtiDomainAdapter().normalize(manifest)
    assert batch.quarantine_counts["unsupported-granular-selector"] == 1


def test_malformed_relationship_is_quarantined_not_silently_dropped_or_batch_fatal():
    manifest = _legacy()
    manifest["relations"][0]["normalized_relation"] = "causes_everything"
    batch = CtiDomainAdapter().normalize(manifest)
    assert batch.quarantine_counts["malformed-relation"] == 1
    assert len(batch.objects) == 5
    assert len(batch.relations) == 3


def test_unmarked_data_requires_explicit_source_contract():
    manifest = _legacy()
    manifest["unmarked_data_public"] = False
    batch = CtiDomainAdapter().normalize(manifest)
    assert not batch.objects
    assert batch.quarantine_counts["unmarked-source-not-public"] == 5


def test_two_sources_sharing_names_never_share_identity():
    first_manifest = _legacy()
    second_manifest = _legacy()
    second_manifest["source_instance"] = "fixture-public-2"
    first = CtiDomainAdapter().normalize(first_manifest)
    second = CtiDomainAdapter().normalize(second_manifest)
    assert first.objects[0].name == second.objects[0].name
    assert first.objects[0].uid != second.objects[0].uid
    assert first.objects[0].uid == object_uid("cti", "fixture-public", "fixture-cve-2026-999999")


def test_corpus_qrels_and_path_annotations_are_separate_from_retrieval_inputs():
    batch = load_cti_corpus_fixture(ROOT / "corpus.manifest.json")
    assert len(batch.objects) == 7
    corpus = (ROOT / "corpus" / "objects.jsonl").read_text(encoding="utf-8").lower()
    queries = (ROOT / "queries" / "queries.jsonl").read_text(encoding="utf-8").lower()
    for forbidden in ('"answer"', '"ground_truth"', '"qrels"', '"relevance"'):
        assert forbidden not in corpus
        assert forbidden not in queries
    annotations = json.loads((ROOT / "annotations" / "paths.json").read_text(encoding="utf-8"))
    assert len(annotations["paths"][0]["ordered_object_uids"]) == 4
    assert len(annotations["paths"][0]["relation_kinds"]) == 3


def test_valid_restricted_object_is_preserved_for_later_policy_denial():
    batch = load_cti_corpus_fixture(ROOT / "corpus.manifest.json")
    restricted = next(obj for obj in batch.objects if obj.source_refs[0].source_object_id == "fixture-restricted-1")
    assert restricted.policy.dissemination == ("tlp:amber",)
