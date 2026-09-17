"""Deterministic native evaluation metrics for the advanced retrieval path."""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Iterable, Mapping, Sequence

from benchmark.advanced.report import MetricResult, MetricStatus


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values))


def _not_applicable(reason: str, coverage: float | None = None) -> MetricResult:
    return MetricResult(
        status=MetricStatus.NOT_APPLICABLE,
        reason=reason,
        support_count=0,
        annotation_coverage=coverage,
        value=None,
    )


def hit_at_k(ranked_targets: Sequence[str], relevant: Iterable[str], k: int) -> MetricResult:
    relevant_set = set(_dedupe(relevant))
    if not relevant_set:
        return _not_applicable("query has no target-object qrels", 0.0)
    ranked = _dedupe(ranked_targets)[:k]
    value = 1.0 if any(item in relevant_set for item in ranked) else 0.0
    return MetricResult(status=MetricStatus.OK, support_count=1, annotation_coverage=1.0, value=value)


def recall_at_k(ranked_targets: Sequence[str], relevant: Iterable[str], k: int) -> MetricResult:
    relevant_set = set(_dedupe(relevant))
    if not relevant_set:
        return _not_applicable("query has no target-object qrels", 0.0)
    ranked = set(_dedupe(ranked_targets)[:k])
    return MetricResult(
        status=MetricStatus.OK,
        support_count=1,
        annotation_coverage=1.0,
        value=len(ranked & relevant_set) / len(relevant_set),
    )


def mrr_at_k(ranked_targets: Sequence[str], relevant: Iterable[str], k: int) -> MetricResult:
    relevant_set = set(_dedupe(relevant))
    if not relevant_set:
        return _not_applicable("query has no target-object qrels", 0.0)
    for index, item in enumerate(_dedupe(ranked_targets)[:k], start=1):
        if item in relevant_set:
            return MetricResult(status=MetricStatus.OK, support_count=1, annotation_coverage=1.0, value=1.0 / index)
    return MetricResult(status=MetricStatus.OK, support_count=1, annotation_coverage=1.0, value=0.0)


def ndcg_at_k(ranked_targets: Sequence[str], graded_relevance: Mapping[str, float], k: int) -> MetricResult:
    positive = {str(key): float(value) for key, value in graded_relevance.items() if float(value) > 0}
    if not positive:
        return _not_applicable("query has no graded target-object qrels", 0.0)

    def dcg(gains: Sequence[float]) -> float:
        return sum((2.0 ** gain - 1.0) / math.log2(index + 1.0) for index, gain in enumerate(gains, start=1))

    ranking = _dedupe(ranked_targets)[:k]
    observed = dcg([positive.get(item, 0.0) for item in ranking])
    ideal = dcg(sorted(positive.values(), reverse=True)[:k])
    value = 0.0 if ideal == 0 else observed / ideal
    return MetricResult(status=MetricStatus.OK, support_count=1, annotation_coverage=1.0, value=value)


def complete_path_hit(
    predicted_paths: Iterable[Sequence[str]],
    acceptable_paths: Iterable[Sequence[str]],
) -> MetricResult:
    gold = {tuple(path) for path in acceptable_paths if path}
    if not gold:
        return _not_applicable("query has no complete-path annotations", 0.0)
    predicted = {tuple(path) for path in predicted_paths if path}
    return MetricResult(
        status=MetricStatus.OK,
        support_count=1,
        annotation_coverage=1.0,
        value=1.0 if predicted & gold else 0.0,
    )


def evidence_recall_at_k(
    ranked_evidence_ids: Sequence[str],
    evidence_labels: Iterable[str] | None,
    k: int,
) -> MetricResult:
    if evidence_labels is None:
        return _not_applicable("separate evidence-document labels are unavailable", 0.0)
    labels = set(_dedupe(evidence_labels))
    if not labels:
        return _not_applicable("query has no evidence-document labels", 0.0)
    ranked = set(_dedupe(ranked_evidence_ids)[:k])
    return MetricResult(
        status=MetricStatus.OK,
        support_count=1,
        annotation_coverage=1.0,
        value=len(ranked & labels) / len(labels),
    )


def citation_validity(valid_flags: Sequence[bool]) -> MetricResult:
    if not valid_flags:
        return _not_applicable("no citations emitted", 0.0)
    return MetricResult(
        status=MetricStatus.OK,
        support_count=len(valid_flags),
        annotation_coverage=1.0,
        value=sum(bool(item) for item in valid_flags) / len(valid_flags),
    )


def citation_support(
    judged_support: Sequence[bool | None],
) -> MetricResult:
    if not judged_support:
        return _not_applicable("no citation-support judgments", 0.0)
    judged = [item for item in judged_support if item is not None]
    coverage = len(judged) / len(judged_support)
    if not judged:
        return MetricResult(
            status=MetricStatus.NOT_RUN,
            reason="citation validity exists but independent support judgments are unavailable",
            support_count=0,
            annotation_coverage=coverage,
            value=None,
        )
    return MetricResult(
        status=MetricStatus.OK,
        support_count=len(judged),
        annotation_coverage=coverage,
        value=sum(bool(item) for item in judged) / len(judged),
    )


def unanswerable_metrics(
    records: Sequence[tuple[bool, bool, bool]],
) -> dict[str, MetricResult]:
    """Records are `(is_unanswerable, emitted_evidence, abstained)` tuples."""
    subset = [item for item in records if item[0]]
    if not subset:
        na = _not_applicable("no unanswerable annotations", 0.0)
        return {"false_evidence_rate": na, "abstention_rate": na}
    count = len(subset)
    return {
        "false_evidence_rate": MetricResult(
            status=MetricStatus.OK,
            support_count=count,
            annotation_coverage=1.0,
            value=sum(item[1] for item in subset) / count,
        ),
        "abstention_rate": MetricResult(
            status=MetricStatus.OK,
            support_count=count,
            annotation_coverage=1.0,
            value=sum(item[2] for item in subset) / count,
        ),
    }


@dataclass(frozen=True)
class BootstrapInterval:
    mean: float
    lower_95: float
    upper_95: float
    resamples: int
    seed: int
    cluster_count: int


def paired_cluster_bootstrap(
    paired_differences_by_cluster: Mapping[str, Sequence[float]],
    *,
    resamples: int = 2000,
    seed: int = 20260917,
) -> BootstrapInterval | None:
    clusters = sorted((str(key), tuple(float(value) for value in values)) for key, values in paired_differences_by_cluster.items() if values)
    if len(clusters) < 2:
        return None
    rng = random.Random(seed)
    observed_values = [value for _, values in clusters for value in values]
    observed = sum(observed_values) / len(observed_values)
    samples: list[float] = []
    for _ in range(resamples):
        selected = [clusters[rng.randrange(len(clusters))][1] for _ in range(len(clusters))]
        flat = [value for values in selected for value in values]
        samples.append(sum(flat) / len(flat))
    samples.sort()
    lo = samples[max(0, math.floor(0.025 * (len(samples) - 1)))]
    hi = samples[min(len(samples) - 1, math.ceil(0.975 * (len(samples) - 1)))]
    return BootstrapInterval(observed, lo, hi, resamples, seed, len(clusters))


def noninferiority_result(interval: BootstrapInterval | None, *, margin: float = -0.01) -> MetricResult:
    if interval is None:
        return MetricResult(
            status=MetricStatus.INCONCLUSIVE,
            reason="fewer than two independent clusters for paired bootstrap",
            support_count=0,
            annotation_coverage=None,
            value=None,
        )
    if interval.lower_95 < margin:
        return MetricResult(
            status=MetricStatus.INCONCLUSIVE,
            reason=f"lower 95% bound {interval.lower_95:.6f} is below preregistered margin {margin:.6f}",
            support_count=interval.cluster_count,
            annotation_coverage=1.0,
            value=None,
        )
    return MetricResult(
        status=MetricStatus.OK,
        support_count=interval.cluster_count,
        annotation_coverage=1.0,
        value=interval.mean,
    )


__all__ = [
    "BootstrapInterval",
    "citation_support",
    "citation_validity",
    "complete_path_hit",
    "evidence_recall_at_k",
    "hit_at_k",
    "mrr_at_k",
    "ndcg_at_k",
    "noninferiority_result",
    "paired_cluster_bootstrap",
    "recall_at_k",
    "unanswerable_metrics",
]
