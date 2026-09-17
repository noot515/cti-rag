"""One-command offline native retrieval evaluation with honest unavailable gates."""
from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any, Iterable, Mapping, Sequence

import yaml

from benchmark.advanced.ablations import (
    l0_comparator_metadata,
    native_ablation_matrix,
    validate_fair_matrix,
)
from benchmark.advanced.metrics import (
    complete_path_hit,
    hit_at_k,
    mrr_at_k,
    ndcg_at_k,
    paired_cluster_bootstrap,
    recall_at_k,
)
from benchmark.advanced.report import MetricResult, MetricStatus
from benchmark.advanced.splits import QueryGrouping, grouped_split
from packages.domains.cti import CtiDomainAdapter
from packages.evidence.config import AdvancedRagConfig, load_advanced_rag_config
from packages.evidence.policy import Principal, PublicFixturePolicy, require_authorized
from packages.evidence.schema import AuthorizedEvidenceView, EvidencePolicyMetadata, SnapshotRef
from packages.evidence.store import EvidenceStore
from packages.indexing.chunker import DeterministicTokenizer
from packages.indexing.cli import ingest_fixture
from packages.indexing.manifests import GenerationManifest
from packages.retrieval.dense import DenseIndex
from packages.retrieval.exact import ExactIndex
from packages.retrieval.graph import CatalogNeighborReader, GraphSearchEngine
from packages.retrieval.lexical import LexicalIndex
from packages.retrieval.planner import DeterministicQueryPlanner
from packages.retrieval.providers import DeterministicFixtureEmbeddingProvider


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "cti"
QUERY_PATH = FIXTURE_ROOT / "queries" / "queries.jsonl"
QRELS_PATH = FIXTURE_ROOT / "qrels" / "objects.json"
PATH_ANNOTATIONS = FIXTURE_ROOT / "annotations" / "paths.json"
CORPUS_MANIFEST = FIXTURE_ROOT / "corpus.manifest.json"


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _write_json(path: Path, payload: Any) -> None:
    _atomic_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )


def _unavailable(status: MetricStatus, reason: str) -> MetricResult:
    return MetricResult(
        status=status,
        reason=reason,
        support_count=0,
        annotation_coverage=0.0,
        value=None,
    )


def _load_queries() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    forbidden = {"answer", "ground_truth", "ground_truth_answer", "qrels", "relevance", "label"}
    for line in QUERY_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("schema_version") != "query-record-v1":
            raise ValueError("unexpected fixture query schema")
        if forbidden & set(record):
            raise ValueError("retrieval runner received an answer-bearing query record")
        if forbidden & set((record.get("options") or {})):
            raise ValueError("retrieval runner received answer labels in query options")
        records.append(record)
    return records


def _groupings(
    queries: Sequence[Mapping[str, Any]], adapter: CtiDomainAdapter
) -> tuple[QueryGrouping, ...]:
    rows: list[QueryGrouping] = []
    for record in queries:
        identifiers = adapter.parse_identifiers(str(record["query"]))
        keys = tuple(f"{item.namespace}:{item.value}" for item in identifiers)
        task_hint = str((record.get("options") or {}).get("task_hint", "general"))
        cluster = "ids:" + "|".join(sorted(keys)) if keys else f"query:{record['query_id']}"
        family_anchor = keys[0] if keys else str(record["query_id"])
        rows.append(
            QueryGrouping(
                query_id=str(record["query_id"]),
                object_cluster=cluster,
                near_duplicate_family=f"{task_hint}:{family_anchor}",
            )
        )
    return tuple(rows)


def _fixture_policy(config: AdvancedRagConfig):
    policy = PublicFixturePolicy.trusted(
        corpus_id=config.source.corpus_id,
        scope_id=config.source.scope_id,
        source_allowlist=frozenset(config.source.source_allowlist),
    )
    principal = Principal(
        principal_id="advanced-eval-fixture",
        source="trusted_local_cli",
        capabilities=frozenset({"eval:fixture"}),
    )
    return policy, policy.resolve_scope(principal, config.source.corpus_id)


def _provider(config: AdvancedRagConfig) -> DeterministicFixtureEmbeddingProvider:
    embedding = config.providers.embedding
    return DeterministicFixtureEmbeddingProvider(
        dimensions=embedding.dimension,
        metric=embedding.metric,
        normalization=embedding.normalization,
        revision=embedding.revision,
        document_instruction=embedding.document_instruction,
        query_instruction=embedding.query_instruction,
        tokenizer=embedding.tokenizer,
    )


def _active_manifest(store: EvidenceStore, config: AdvancedRagConfig) -> GenerationManifest:
    row = store.connection.execute(
        "SELECT gm.manifest_json FROM active_generations ag JOIN generation_manifests gm "
        "ON gm.domain=ag.domain AND gm.scope_id=ag.scope_id AND gm.corpus_id=ag.corpus_id "
        "AND gm.generation_id=ag.generation_id "
        "WHERE ag.domain=? AND ag.scope_id=? AND ag.corpus_id=?",
        ("cti", config.source.scope_id, config.source.corpus_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("fixture evaluation requires an active published generation")
    return GenerationManifest.model_validate_json(row["manifest_json"])


def _object_hit_allowed(
    store: EvidenceStore, policy: Any, scope: Any, hit: Any
) -> bool:
    revision_uid = str(hit.metadata["object_revision_uid"])
    row = store.get_revision(hit.domain, hit.scope_id, revision_uid)
    if row is None:
        return False
    payload = row["payload"]
    view = AuthorizedEvidenceView(
        evidence_uid=revision_uid,
        domain=hit.domain,
        scope_id=hit.scope_id,
        source_instances=tuple(
            sorted(
                {
                    str(item["source_instance"])
                    for item in row.get("sources") or []
                    if item.get("source_instance")
                }
            )
        ),
        policy=EvidencePolicyMetadata.model_validate(payload.get("policy") or {}),
    )
    try:
        require_authorized(policy.authorize_evidence(view, scope, "caller"))
        return True
    except PermissionError:
        return False


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def _rrf(rankings: Sequence[Sequence[str]]) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, target in enumerate(_dedupe(ranking), start=1):
            scores[target] = scores.get(target, 0.0) + 1.0 / (60.0 + rank)
    return [
        target
        for target, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ]


def _predict_fixture_queries(
    *, config_path: Path, config: AdvancedRagConfig
) -> tuple[
    list[dict[str, Any]],
    dict[str, QueryGrouping],
    dict[str, Any],
]:
    """Execute all native retrieval before qrels/path annotations are opened."""
    ingest_report = ingest_fixture(
        config_path=config_path,
        manifest_path=CORPUS_MANIFEST,
    )
    adapter = CtiDomainAdapter()
    planner = DeterministicQueryPlanner(adapter)
    queries = _load_queries()
    groupings = _groupings(queries, adapter)
    grouping_by_id = {item.query_id: item for item in groupings}
    # Freeze the deterministic grouped split before retrieval or evaluation. The
    # returned manifest is written later, but its seed/hashes are determined here.
    frozen_split = grouped_split(groupings)
    policy, scope = _fixture_policy(config)
    provider = _provider(config)
    tokenizer = DeterministicTokenizer()
    state_dir = Path(config.state_dir)
    predictions: list[dict[str, Any]] = []

    with EvidenceStore(state_dir / "catalog.db", state_dir / "raw") as store:
        manifest = _active_manifest(store, config)
        snapshot = SnapshotRef(
            domain=manifest.domain,
            scope_id=manifest.scope_id,
            snapshot_id=manifest.generation_id,
            manifest_sha256=manifest.manifest_sha256,
        )
        index_root = state_dir / "indexes"
        exact = ExactIndex.open(
            store,
            path=ExactIndex.path_for(
                index_root,
                domain=manifest.domain,
                scope_id=manifest.scope_id,
                generation_id=manifest.generation_id,
            ),
        )
        lexical = LexicalIndex.open(
            store,
            path=LexicalIndex.path_for(
                index_root,
                domain=manifest.domain,
                scope_id=manifest.scope_id,
                generation_id=manifest.generation_id,
            ),
            tokenizer=tokenizer,
        )
        dense = DenseIndex.open(
            store,
            path=DenseIndex.path_for(
                index_root,
                domain=manifest.domain,
                scope_id=manifest.scope_id,
                generation_id=manifest.generation_id,
            ),
            provider=provider,
        )
        patterns = {
            pattern.pattern_id: pattern
            for hint in ("general", "mapping", "three_hop_mapping")
            for pattern in adapter.allowed_graph_patterns(hint)
        }
        graph = GraphSearchEngine(
            CatalogNeighborReader(store),
            allowed_pattern_ids=frozenset(patterns),
        )

        for record in queries:
            query_id = str(record["query_id"])
            query = str(record["query"])
            started = time.monotonic()
            rankings: dict[str, list[str]] = {
                "exact": [],
                "lexical": [],
                "dense": [],
                "graph": [],
            }
            predicted_paths: list[list[str]] = []
            errors: list[str] = []
            task = "unknown"
            try:
                identifiers = adapter.parse_identifiers(query)
                task = adapter.infer_task_hint(query, identifiers)

                exact_hits: list[Any] = []
                for identifier in identifiers:
                    exact_hits.extend(
                        exact.lookup(
                            identifier,
                            scope=scope,
                            snapshot=snapshot,
                            top_k=config.channels.exact_top_k,
                        )
                    )
                exact_hits.sort(
                    key=lambda hit: (
                        int(hit.metadata.get("rank", 1)),
                        str(hit.metadata.get("object_uid", "")),
                    )
                )
                rankings["exact"] = _dedupe(
                    str(hit.metadata["object_uid"])
                    for hit in exact_hits
                    if _object_hit_allowed(store, policy, scope, hit)
                )

                for hit in lexical.search(
                    query,
                    scope=scope,
                    snapshot=snapshot,
                    top_k=config.channels.lexical_top_k,
                ):
                    try:
                        lexical.hydrate(
                            hit,
                            scope=scope,
                            snapshot=snapshot,
                            policy=policy,
                        )
                    except PermissionError:
                        continue
                    rankings["lexical"].append(str(hit.metadata["object_uid"]))
                rankings["lexical"] = _dedupe(rankings["lexical"])

                for hit in dense.search(
                    query,
                    provider=provider,
                    scope=scope,
                    snapshot=snapshot,
                    destination="local_generator",
                    top_k=config.channels.dense_top_k,
                    deadline=time.monotonic() + config.timeouts.channel_seconds,
                ):
                    try:
                        candidate = dense.candidate_for_hit(
                            hit,
                            scope=scope,
                            snapshot=snapshot,
                            policy=policy,
                        )
                    except PermissionError:
                        continue
                    rankings["dense"].append(candidate.object_uid)
                rankings["dense"] = _dedupe(rankings["dense"])

                plan = planner.plan(
                    query,
                    authorized_seed_ids=rankings["exact"],
                    max_graph_hops=config.graph.max_mapping_hops,
                    top_k=12,
                    lexical_enabled=True,
                    dense_enabled=True,
                )
                if plan.graph_enabled:
                    for pattern_id in plan.pattern_ids:
                        search = graph.search(
                            manifest=manifest,
                            pattern=patterns[pattern_id],
                            authorized_seed_ids=plan.authorized_seed_ids,
                            scope=scope,
                            snapshot=snapshot,
                            policy=policy,
                            deadline=time.monotonic() + config.timeouts.channel_seconds,
                            max_hops=plan.bounds.max_graph_hops,
                        )
                        for path in search.paths:
                            predicted_paths.append(list(path.ordered_node_uids))
                            rankings["graph"].append(path.ordered_node_uids[-1])
                    rankings["graph"] = _dedupe(rankings["graph"])
            except Exception as exc:
                # A failed query remains in per_query and later metric denominators.
                errors.append(type(exc).__name__)

            ablations = {
                "R1": list(rankings["dense"]),
                "R2": list(rankings["lexical"]),
                "R3": _rrf((rankings["dense"], rankings["lexical"])),
                "R4": _rrf(
                    (rankings["dense"], rankings["lexical"], rankings["exact"])
                ),
                "R5": _rrf(
                    (
                        rankings["dense"],
                        rankings["lexical"],
                        rankings["exact"],
                        rankings["graph"],
                    )
                ),
            }
            predictions.append(
                {
                    "query_id": query_id,
                    "query": query,
                    "task": task,
                    "execution_status": "failed" if errors else "ok",
                    "execution_errors": errors,
                    "latency_ms": max(
                        0.0,
                        (time.monotonic() - started) * 1000.0,
                    ),
                    "channel_rankings": rankings,
                    "rankings": ablations,
                    "predicted_paths": predicted_paths,
                    "R6_status": "not_run",
                    "R6_reason": (
                        "fixture configuration has no explicit reranker provider; "
                        "R6 quality is not fabricated"
                    ),
                    "C1_status": "not_run",
                    "C1_reason": (
                        "C1 answer/context comparison requires the unavailable final "
                        "reranker/generator evaluation stage"
                    ),
                }
            )

    return (
        predictions,
        grouping_by_id,
        {
            **ingest_report,
            "frozen_split": frozen_split.as_dict(),
        },
    )


def _aggregate(results: Sequence[MetricResult], *, reason: str) -> MetricResult:
    applicable = [
        item
        for item in results
        if item.status == MetricStatus.OK and item.value is not None
    ]
    if not applicable:
        status = (
            MetricStatus.NOT_APPLICABLE
            if results and {item.status for item in results} == {MetricStatus.NOT_APPLICABLE}
            else MetricStatus.NOT_RUN
        )
        return _unavailable(status, reason)
    return MetricResult(
        status=MetricStatus.OK,
        support_count=len(applicable),
        annotation_coverage=len(applicable) / len(results),
        value=sum(float(item.value) for item in applicable) / len(applicable),
    )


def _evaluate_predictions(
    predictions: list[dict[str, Any]],
    grouping_by_id: Mapping[str, QueryGrouping],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Open evaluation-only labels only after native predictions are immutable records."""
    qrels = json.loads(QRELS_PATH.read_text(encoding="utf-8")).get("qrels", {})
    annotations = json.loads(PATH_ANNOTATIONS.read_text(encoding="utf-8"))
    paths_by_query: dict[str, list[list[str]]] = {}
    for item in annotations.get("paths", []):
        paths_by_query.setdefault(str(item["query_id"]), []).append(
            list(item["ordered_object_uids"])
        )

    names = ("R1", "R2", "R3", "R4", "R5")
    keys = ("hit@1", "hit@5", "recall@10", "mrr@10", "ndcg@10", "complete_path")
    buckets = {name: {key: [] for key in keys} for name in names}
    recall_by_query: dict[str, dict[str, float | None]] = {}

    for record in predictions:
        query_id = str(record["query_id"])
        labels = list(qrels.get(query_id, []))
        recall_by_query[query_id] = {}
        record["evaluation"] = {}
        for name in names:
            ranking = record["rankings"][name]
            metrics = {
                "hit@1": hit_at_k(ranking, labels, 1),
                "hit@5": hit_at_k(ranking, labels, 5),
                "recall@10": recall_at_k(ranking, labels, 10),
                "mrr@10": mrr_at_k(ranking, labels, 10),
                "ndcg@10": ndcg_at_k(
                    ranking,
                    {item: 1.0 for item in labels},
                    10,
                ),
                "complete_path": complete_path_hit(
                    record["predicted_paths"] if name == "R5" else (),
                    paths_by_query.get(query_id, ()),
                ),
            }
            record["evaluation"][name] = {
                key: metric.model_dump(mode="json")
                for key, metric in metrics.items()
            }
            recall_by_query[query_id][name] = metrics["recall@10"].value
            for key, metric in metrics.items():
                buckets[name][key].append(metric)
        record["evaluation"]["evidence_document_recall@10"] = _unavailable(
            MetricStatus.NOT_APPLICABLE,
            "fixture has target-object qrels but no independent evidence-document labels",
        ).model_dump(mode="json")

    aggregate: dict[str, Any] = {
        name: {
            key: _aggregate(values, reason=f"no applicable {key} annotations").model_dump(
                mode="json"
            )
            for key, values in metric_map.items()
        }
        for name, metric_map in buckets.items()
    }
    r6 = _unavailable(
        MetricStatus.NOT_RUN,
        "fixture has no configured final reranker provider",
    ).model_dump(mode="json")
    aggregate["R6"] = {key: dict(r6) for key in keys}
    c1 = _unavailable(
        MetricStatus.NOT_RUN,
        "no final reranker/generator context-quality evaluation configured",
    ).model_dump(mode="json")
    aggregate["C1-basic"] = {"context_quality": dict(c1)}
    aggregate["C1-structured"] = {"context_quality": dict(c1)}
    aggregate["L0"] = {
        "object_recall@10": _unavailable(
            MetricStatus.NOT_COMPARABLE,
            "L0 canonical object mapping is unavailable for this fixture comparator",
        ).model_dump(mode="json")
    }
    aggregate["evidence_document_metrics"] = {
        "status": "not_applicable",
        "reason": "no separate evidence-document labels",
    }
    aggregate["unanswerable"] = {
        "false_evidence_rate": _unavailable(
            MetricStatus.NOT_APPLICABLE,
            "fixture has no independent unanswerable-query annotation set",
        ).model_dump(mode="json"),
        "abstention_rate": _unavailable(
            MetricStatus.NOT_APPLICABLE,
            "fixture has no independent unanswerable-query annotation set",
        ).model_dump(mode="json"),
    }

    # Graph-gain uses mapping queries only, grouped by the frozen near-duplicate
    # family. It is intentionally distinct from held-out-edge generalization.
    graph_differences: dict[str, list[float]] = {}
    for record in predictions:
        if record.get("task") != "mapping":
            continue
        query_id = str(record["query_id"])
        r5 = recall_by_query[query_id].get("R5")
        r4 = recall_by_query[query_id].get("R4")
        if r5 is None or r4 is None:
            continue
        family = grouping_by_id[query_id].near_duplicate_family
        graph_differences.setdefault(family, []).append(float(r5) - float(r4))
    graph_interval = paired_cluster_bootstrap(graph_differences)
    if graph_interval is None:
        graph_gain = _unavailable(
            MetricStatus.INCONCLUSIVE,
            "mapping-subset graph gain has fewer than two independent query-family clusters",
        )
    elif graph_interval.lower_95 > 0.0:
        graph_gain = MetricResult(
            status=MetricStatus.OK,
            support_count=graph_interval.cluster_count,
            annotation_coverage=1.0,
            value=graph_interval.mean,
        )
    else:
        graph_gain = MetricResult(
            status=MetricStatus.INCONCLUSIVE,
            reason=(
                f"mapping-subset graph-gain lower 95% bound "
                f"{graph_interval.lower_95:.6f} is not greater than zero"
            ),
            support_count=graph_interval.cluster_count,
            annotation_coverage=1.0,
            value=None,
        )

    aggregate["gates"] = {
        "R6_vs_R5_recall10_noninferiority": _unavailable(
            MetricStatus.NOT_RUN,
            "R6 unavailable without an explicit reranker provider/model",
        ).model_dump(mode="json"),
        "R5_vs_R4_mapping_graph_gain": graph_gain.model_dump(mode="json"),
        "held_out_edge_generalization": _unavailable(
            MetricStatus.NOT_RUN,
            "catalog fixture mapping is not a held-out-edge experiment",
        ).model_dump(mode="json"),
        "real_quality_promotion": _unavailable(
            MetricStatus.NOT_RUN,
            "synthetic fixture establishes mechanics only; real held-out quality gates were not run",
        ).model_dump(mode="json"),
    }
    return aggregate, predictions


def _report_files(
    *,
    output: Path,
    config: AdvancedRagConfig,
    predictions: list[dict[str, Any]],
    ingest_report: Mapping[str, Any],
    retrieval_metrics: Mapping[str, Any],
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    # Serialize the validated model, not the raw file/environment, so secret-like
    # unknown keys can never leak into a report snapshot.
    _atomic_text(
        output / "config.snapshot.yaml",
        yaml.safe_dump(config.serializable_snapshot(), sort_keys=True),
    )
    _write_json(
        output / "environment.json",
        {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "concurrency": 1,
            "cache_state": "fixture-local-persistent-index-reopen",
            "network_used": False,
            "throughput_claim": False,
            "embedding_model": config.providers.embedding.model,
            "embedding_revision": config.providers.embedding.revision,
            "reranker": None,
            "generator": None,
            "judge": None,
        },
    )
    _write_json(
        output / "corpus.manifest.snapshot.json",
        {
            "sha256": _sha256(CORPUS_MANIFEST),
            "manifest": json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8")),
            "ingest_report": {
                key: value
                for key, value in ingest_report.items()
                if key != "frozen_split"
            },
        },
    )
    _write_json(output / "split.manifest.json", ingest_report["frozen_split"])
    _atomic_text(
        output / "per_query.jsonl",
        "".join(
            json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n"
            for item in predictions
        ),
    )
    _write_json(output / "retrieval_metrics.json", retrieval_metrics)
    latencies = [float(item["latency_ms"]) for item in predictions]
    _write_json(
        output / "latency_metrics.json",
        {
            "status": "ok" if latencies else "not_run",
            "sample_count": len(latencies),
            "concurrency": 1,
            "cache_state": "fixture-local-persistent-index-reopen",
            "mean_ms": sum(latencies) / len(latencies) if latencies else None,
            "max_ms": max(latencies) if latencies else None,
            "throughput_reported": False,
        },
    )
    _write_json(
        output / "answer_metrics.json",
        {
            "answer_quality": _unavailable(
                MetricStatus.NOT_RUN,
                "retrieval evaluation does not invoke a generator",
            ).model_dump(mode="json"),
            "citation_validity": _unavailable(
                MetricStatus.NOT_RUN,
                "retrieval-only runner emits no generated response citations",
            ).model_dump(mode="json"),
            "citation_support": _unavailable(
                MetricStatus.NOT_RUN,
                "no independent answer/citation support judgments configured",
            ).model_dump(mode="json"),
        },
    )

    specs = native_ablation_matrix()
    validate_fair_matrix(specs)
    with (output / "ablation_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "name",
                "description",
                "status",
                "recall10",
                "top_k",
                "pre_rerank_limit",
                "context_budget",
            ],
        )
        writer.writeheader()
        for spec in specs:
            metric = retrieval_metrics.get(spec.name, {}).get("recall@10")
            writer.writerow(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "status": metric.get("status") if metric else "not_run",
                    "recall10": metric.get("value") if metric else None,
                    "top_k": spec.top_k,
                    "pre_rerank_limit": spec.pre_rerank_limit,
                    "context_budget": spec.context_budget,
                }
            )

    l0 = l0_comparator_metadata(canonical_mapping_available=False)
    report = [
        "# Advanced fixture retrieval evaluation",
        "",
        "This is a deterministic synthetic-fixture mechanics report, not a real-quality promotion claim.",
        "",
        f"- queries: {len(predictions)}",
        f"- active generation: {ingest_report.get('generation_id')}",
        (
            "- L0 comparator: comparable"
            if l0["canonical_object_mapping_available"]
            else "- L0 comparator: not_comparable"
        ),
        "- R6 reranker: not_run (no explicit fixture reranker provider)",
        "- C1 answer/context comparison: not_run",
        "- held-out-edge generalization: not_run",
        "- answer/generator/judge quality: not_run",
        "- authorization ablation: forbidden/not performed",
        "- throughput claim: none (sequential fixture run)",
        "",
        "See retrieval_metrics.json, answer_metrics.json, latency_metrics.json, per_query.jsonl and ablation_summary.csv for machine-readable details.",
    ]
    _atomic_text(output / "report.md", "\n".join(report) + "\n")


def run_retrieval_evaluation(
    *, config_path: Path, output: Path
) -> dict[str, Any]:
    config = load_advanced_rag_config(config_path)
    if config.profile != "fixture":
        raise RuntimeError(
            "offline native evaluation currently requires the deterministic fixture profile"
        )
    predictions, groupings, ingest_report = _predict_fixture_queries(
        config_path=config_path,
        config=config,
    )
    metrics, predictions = _evaluate_predictions(predictions, groupings)
    _report_files(
        output=output,
        config=config,
        predictions=predictions,
        ingest_report=ingest_report,
        retrieval_metrics=metrics,
    )
    return {
        "schema_version": "advanced-retrieval-eval-report-v1",
        "output": str(output),
        "queries": len(predictions),
        "real_quality": "not_run",
        "network_used": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic advanced retrieval evaluation"
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_retrieval_evaluation(
        config_path=args.config,
        output=args.output,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
