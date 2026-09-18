from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.cticonnect import adapter as cti


def test_structured_nested_json_uses_source_identifier_not_outer_id():
    cwe = cti.parse_structured_record(
        "cwe",
        {"id": "0", "cwe_id": "79", "title": "XSS", "contents": json.dumps({"Description": "cross site"})},
        relative_path="corpus_kb/cwe.jsonl",
    )
    capec = cti.parse_structured_record(
        "capec",
        {"id": "0", "capec_id": "66", "title": "SQL Injection", "contents": json.dumps({"@ID": "66"})},
        relative_path="corpus_kb/capec.jsonl",
    )
    assert cwe.document_id == "cwe:CWE-79"
    assert capec.document_id == "capec:CAPEC-66"
    assert cwe.provenance["outer_id"] == "0"
    assert capec.provenance["outer_id"] == "0"
    assert cwe.document_id != capec.document_id
    assert '"Description":"cross site"' in cwe.text


def test_malformed_nested_contents_is_rejected():
    with pytest.raises(cti.CTIConnectAuditError, match="nested JSON"):
        cti.parse_structured_record(
            "cve",
            {"id": "7", "cve_id": "CVE-2025-12345", "title": "bad", "contents": "not-json"},
            relative_path="corpus_kb/cve.jsonl",
        )


def test_report_uses_validated_blog_mapping_without_fetching():
    report = cti.parse_report_record(
        {
            "id": 101,
            "title": "Silent Skimmer",
            "publish_date": "2023-05-28",
            "link": "https://example.invalid/report",
            "preprocessed": "summary text",
            "metadata": {"source": "blog"},
        },
        relative_path="corpus_reports/preprocessed_reports.jsonl",
    )
    assert report.document_id == "report:BLOG-101"
    assert report.provenance["blog_id"] == "BLOG-101"
    assert report.provenance["full_text_fetched"] is False
    assert "summary text" in report.text


def test_query_record_does_not_receive_answers_qrels_or_source_cluster(monkeypatch, tmp_path: Path):
    task_dir = tmp_path / "data" / "entity_linking"
    task_dir.mkdir(parents=True)
    record = {
        "id": "rcm-001",
        "task": "rcm",
        "category": "entity_linking",
        "eval_type": "single_id_match",
        "question": "Which weakness applies?",
        "answer": "CWE-79",
        "ground_truth": {"target_type": "cwe", "target_id": "CWE-79"},
        "source": {"source_type": "cve", "source_id": "CVE-2025-12345", "construction_file": "secret-source-cluster.json"},
    }
    (task_dir / "rcm.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        cti,
        "EXPECTED_TASKS",
        {"rcm": {"category": "entity_linking", "count": 1, "eval_type": "single_id_match", "target_type": "cwe", "sha256": "unused"}},
    )
    monkeypatch.setattr(cti, "EXPECTED_TOTAL", 1)
    queries, labels = cti.load_queries_and_labels(tmp_path)
    query = queries[0]
    assert query.query == "Which weakness applies?"
    assert set(query.options) == {"task", "category", "eval_type"}
    serialized = query.model_dump(mode="json")
    assert "ground_truth" not in serialized
    assert "answer" not in serialized
    assert "source" not in serialized
    assert labels["rcm-001"].target_id == "CWE-79"
    assert labels["rcm-001"].construction_file == "secret-source-cluster.json"


def test_official_alternate_target_behavior_and_mixed_invalid_output():
    label = cti.OfficialLabel(
        query_id="atd-1",
        task="atd",
        eval_type="single_id_match",
        target_type="mitre",
        target_id="T1059.001",
        target_ids=(),
        valid_target_ids=("T1059.002",),
        reference_answer=None,
        source_type="capec",
        source_id="CAPEC-66",
        blog_ids=(),
        construction_file=None,
    )
    alternate = cti.official_identifier_score("The answer is T1059.002", label)
    assert alternate.f1 == 1.0
    assert alternate.exact_match is True

    mixed = cti.official_identifier_score("T1059.002 and T9999", label)
    assert mixed.f1 == 0.0
    assert mixed.exact_match is False


def test_qrels_proxies_are_explicit_and_separate():
    label = cti.OfficialLabel(
        query_id="csc-1",
        task="csc",
        eval_type="judge",
        target_type="free_text",
        target_id=None,
        target_ids=(),
        valid_target_ids=(),
        reference_answer="timeline",
        source_type="blog_cluster",
        source_id=None,
        blog_ids=("BLOG-1", "BLOG-2"),
        construction_file=None,
    )
    assert cti.target_document_ids(label) == ()
    assert cti.source_proxy_document_ids(label) == ("report:BLOG-1", "report:BLOG-2")


def test_text_bm25_rebuilds_from_text():
    docs = (
        cti.CorpusDocument("cwe:CWE-79", "cwe", "CWE-79", "XSS", "CWE-79 cross site scripting output encoding", {}),
        cti.CorpusDocument("cwe:CWE-89", "cwe", "CWE-89", "SQL", "CWE-89 SQL query injection database", {}),
    )
    index = cti.TextBM25(docs)
    assert index.search("SQL database injection", top_k=1, corpus_kind="cwe") == ("cwe:CWE-89",)
