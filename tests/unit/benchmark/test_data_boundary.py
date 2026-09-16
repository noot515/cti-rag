from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmark.advanced.dataset import (
    CorpusFile,
    CorpusManifest,
    EvaluationDataError,
    QueryRecord,
    SourceLineage,
    file_sha256,
    validate_corpus_manifest,
)
from benchmark.advanced.report import MetricResult, MetricStatus


def _lineage() -> SourceLineage:
    return SourceLineage(
        source_name="public fixture",
        source_revision="v1",
        license_or_terms="synthetic",
        public_or_sanitized=True,
    )


def test_query_record_rejects_qrels_or_ground_truth_injection():
    with pytest.raises(ValidationError):
        QueryRecord(query_id="q1", query="hello", qrels=["secret"])
    with pytest.raises(ValidationError):
        QueryRecord(query_id="q1", query="hello", ground_truth="answer")
    with pytest.raises(ValidationError, match="evaluation-only"):
        QueryRecord(query_id="q1", query="hello", options={"nested": {"qrels": ["secret"]}})


def test_manifest_rejects_path_traversal():
    with pytest.raises(ValidationError, match="repository-relative"):
        CorpusFile(role="corpus", path="../private.json", sha256="a" * 64,
                   schema_version="v1", lineage=_lineage())


def test_manifest_detects_changed_hash(tmp_path: Path):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps({"schema_version": "v1", "records": [{"name": "safe"}]}), encoding="utf-8")
    manifest = CorpusManifest(corpus_id="c1", files=(CorpusFile(
        path="corpus.json", sha256="a" * 64, schema_version="v1", lineage=_lineage()),))
    with pytest.raises(EvaluationDataError, match="hash mismatch"):
        validate_corpus_manifest(manifest, tmp_path)


def test_manifest_rejects_qa_shaped_corpus_input(tmp_path: Path):
    corpus = tmp_path / "qa.json"
    corpus.write_text(json.dumps({"schema_version": "qa-v1", "records": [{"question": "q", "answer": "a"}]}), encoding="utf-8")
    manifest = CorpusManifest(corpus_id="c1", files=(CorpusFile(
        path="qa.json", sha256=file_sha256(corpus), schema_version="qa-v1", lineage=_lineage()),))
    with pytest.raises(EvaluationDataError, match="QA-shaped"):
        validate_corpus_manifest(manifest, tmp_path)


def test_manifest_rejects_schema_version_mismatch(tmp_path: Path):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps({"schema_version": "actual-v2", "records": []}), encoding="utf-8")
    manifest = CorpusManifest(corpus_id="c1", files=(CorpusFile(
        path="corpus.json", sha256=file_sha256(corpus), schema_version="expected-v1", lineage=_lineage()),))
    with pytest.raises(EvaluationDataError, match="schema_version mismatch"):
        validate_corpus_manifest(manifest, tmp_path)


def test_metric_status_serialization_keeps_unavailable_value_null():
    metric = MetricResult(
        status=MetricStatus.NOT_COMPARABLE,
        reason="canonical mapping unavailable",
        support_count=0,
        value=None,
    )
    payload = metric.model_dump(mode="json")
    assert payload == {
        "status": "not_comparable",
        "reason": "canonical mapping unavailable",
        "support_count": 0,
        "value": None,
    }
    with pytest.raises(ValidationError, match="value=null"):
        MetricResult(status=MetricStatus.NOT_RUN, reason="not run", support_count=0, value=0.0)
