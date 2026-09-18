from __future__ import annotations

import os
from pathlib import Path

import pytest

from benchmark.cticonnect.adapter import (
    EXPECTED_TOTAL,
    PINNED_COMMIT,
    annotation_coverage,
    audit_external_root,
    load_corpus,
    load_queries_and_labels,
)


pytestmark = pytest.mark.integration


def _root() -> Path:
    raw = os.environ.get("CTICONNECT_PATH")
    if not raw:
        pytest.skip("CTICONNECT_PATH is not set")
    return Path(raw)


def test_pinned_cticonnect_inventory_and_corpus_contracts():
    root = _root()
    audit = audit_external_root(root)
    assert audit.commit == PINNED_COMMIT
    assert audit.total_queries == EXPECTED_TOTAL == 1859
    assert audit.task_counts == {
        "rcm": 290, "wim": 308, "atd": 261, "esd": 280,
        "ata": 160, "vca": 219, "csc": 111, "tap": 135, "mla": 95,
    }
    assert audit.report_count == 321
    assert audit.graph_assets["lineage"] == "extracted"
    assert audit.graph_assets["bm25_pickle_consumed"] is False

    documents = load_corpus(root)
    assert len(documents) == 615 + 3011 + 1342 + 1076 + 321
    assert not any(item.provenance.get("graph_lineage") for item in documents)

    queries, labels = load_queries_and_labels(root)
    assert len(queries) == len(labels) == 1859
    coverage = annotation_coverage(labels, {item.document_id for item in documents})
    assert coverage["target_object_queries"] == 1518
    assert coverage["source_proxy_queries"] == 1859
    assert coverage["target_object_coverage"] is not None
    assert coverage["source_proxy_coverage"] is not None
