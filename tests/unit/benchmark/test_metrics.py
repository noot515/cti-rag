from __future__ import annotations

import math

from benchmark.advanced.metrics import (
    citation_support,
    citation_validity,
    complete_path_hit,
    evidence_recall_at_k,
    hit_at_k,
    mrr_at_k,
    ndcg_at_k,
    noninferiority_result,
    paired_cluster_bootstrap,
    recall_at_k,
    unanswerable_metrics,
)
from benchmark.advanced.report import MetricStatus


def test_target_metrics_are_deduplicated_and_first_hit_ordered():
    ranked = ["a", "a", "x", "b"]
    relevant = ["a", "b"]
    assert hit_at_k(ranked, relevant, 1).value == 1.0
    assert recall_at_k(ranked, relevant, 1).value == 0.5
    # Duplicate a does not consume the second unique rank; x is rank 2, b rank 3.
    assert math.isclose(mrr_at_k(["x", "a", "a"], ["a"], 10).value, 0.5)


def test_ndcg_matches_hand_calculated_graded_ranking():
    result = ndcg_at_k(["b", "a", "x"], {"a": 3.0, "b": 1.0}, 3)
    observed = 1.0 + 7.0 / math.log2(3.0)
    ideal = 7.0 + 1.0 / math.log2(3.0)
    assert math.isclose(result.value, observed / ideal, rel_tol=0.0, abs_tol=1e-12)


def test_empty_object_labels_are_not_applicable_not_zero():
    for result in (
        hit_at_k(["a"], [], 1),
        recall_at_k(["a"], [], 10),
        mrr_at_k(["a"], [], 10),
        ndcg_at_k(["a"], {}, 10),
    ):
        assert result.status == MetricStatus.NOT_APPLICABLE
        assert result.value is None


def test_complete_path_requires_an_entire_acceptable_alternative():
    gold = [("a", "b", "c"), ("a", "d", "c")]
    assert complete_path_hit([("a", "b", "c")], gold).value == 1.0
    assert complete_path_hit([("a", "b")], gold).value == 0.0
    assert complete_path_hit([("a", "c")], gold).value == 0.0


def test_evidence_metrics_require_separate_evidence_labels():
    missing = evidence_recall_at_k(["doc-1"], None, 10)
    assert missing.status == MetricStatus.NOT_APPLICABLE
    assert missing.value is None
    assert evidence_recall_at_k(["doc-1", "doc-2"], ["doc-2"], 1).value == 0.0
    assert evidence_recall_at_k(["doc-1", "doc-2"], ["doc-2"], 2).value == 1.0


def test_citation_validity_does_not_imply_independent_support():
    validity = citation_validity([True, True])
    support = citation_support([None, None])
    assert validity.status == MetricStatus.OK
    assert validity.value == 1.0
    assert support.status == MetricStatus.NOT_RUN
    assert support.value is None
    partial = citation_support([True, None, False])
    assert partial.annotation_coverage == 2 / 3
    assert partial.value == 0.5


def test_unanswerable_false_evidence_and_abstention_are_separate():
    metrics = unanswerable_metrics(
        [
            (True, True, False),
            (True, False, True),
            (False, True, False),
        ]
    )
    assert metrics["false_evidence_rate"].value == 0.5
    assert metrics["abstention_rate"].value == 0.5


def test_cluster_bootstrap_is_deterministic_and_noninferiority_uses_lower_bound():
    clusters = {
        "c1": [0.02, 0.01],
        "c2": [0.03],
        "c3": [0.00, 0.02],
    }
    first = paired_cluster_bootstrap(clusters, resamples=2000, seed=17)
    second = paired_cluster_bootstrap(clusters, resamples=2000, seed=17)
    assert first == second
    assert first is not None
    result = noninferiority_result(first, margin=-0.01)
    assert result.status == MetricStatus.OK


def test_small_bootstrap_data_is_inconclusive():
    interval = paired_cluster_bootstrap({"only-one": [0.1]})
    assert interval is None
    result = noninferiority_result(interval)
    assert result.status == MetricStatus.INCONCLUSIVE
    assert result.value is None
