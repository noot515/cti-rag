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
from packages.evidence.schema import (
    AuthorizedEvidenceView,
    EvidencePolicyMetadata,
    SnapshotRef,
)
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
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def _write_json(path: Path, payload: Any) -> None:
    _atomic_text(path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _load_queries() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in QUERY_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("schema_version") != "query-record-v1":
            raise ValueError("unexpected fixture query schema")
        forbidden = {"answer", "ground_truth", "qrels", "relevance", "label"}
        if forbidden & set(record):
            raise ValueError("retrieval runner received an answer-bearing query record")
        records.append(record)
    return records


def _groupings(queries: Sequence[Mapping[str, Any]], adapter: CtiDomainAdapter) -> tuple[QueryGrouping, ...]:
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


def _scope(config: AdvancedRagConfig):
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
        "AND gm.generation_id=ag.generation_id WHERE ag.domain=? AND ag.scope_id=? AND ag.corpus_id=?",
        ("cti", config.source.scope_id, config.source.corpus_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("fixture evaluation requires an active published generation")
    return GenerationManifest.model_validate_json(row["manifest_json"])


def _object_hit_allowed(store, policy, scope, hit) -> bool:
    revision_uid = str(hit.metadata["object_revision_uid"])
    row = store.get_revision(hit.domain, hit.scope_id, revision_uid)
    if row is None:
        return False
    payload = row["payload"]
    sources = row.get("sources") or []
    view = AuthorizedEvidenceView(
        evidence_uid=revision_uid,
        domain=hit.domain,
        scope_id=hit.scope_id,
        source_instances=tuple(sorted({str(item["source_instance"]) for item in sources if item.get("source_instance")})),
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
    return [target for target, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]


def _predict_fixture_queries(config: AdvancedRagConfig) -> tuple[list[dict[str, Any]], dict[str, QueryGrouping], dict[str, Any]]:
    # Corpus/query execution happens before qrels or path annotations are loaded.
    ingest_report = ingest_fixture(config_path=Path(config.config_path) if hasattr(config, "config_path") else Path("benchmark/advanced/configs/fixture.yaml"), manifest_path=CORPUS_MANIFEST)
    state_dir = Path(config.state_dir)
    adapter = CtiDomainAdapter()
    planner = DeterministicQueryPlanner(adapter)
    queries = _load_queries()
    grouping_rows = _groupings(queries, adapter)
    grouping_by_id = {row.query_id: row for row in grouping_rows}
    policy, scope = _scope(config)
    provider = _provider(config)
    tokenizer = DeterministicTokenizer()
    predictions: list[dict[str, Any]] = []

    with EvidenceStore(state_dir / "catalog.db", state_dir / "raw") as store:
        manifest = _active_manifest(store, config)
        snapshot = SnapshotRef(
            domain=manifest.domain,
            scope_id=manifest.scope_id,
            snapshot_id=manifest.generation_id,
            manifest_sha256=manifest.manifest_sha256,
        )
        root = state_dir / "indexes"
        exact = ExactIndex.open(
            store,
            path=ExactIndex.path_for(root, domain=manifest.domain, scope_id=manifest.scope_id, generation_id=manifest.generation_id),
        )
        lexical = LexicalIndex.open(
            store,
            path=LexicalIndex.path_for(root, domain=manifest.domain, scope_id=manifest.scope_id, generation_id=manifest.generation_id),
            tokenizer=tokenizer,
        )
        dense = DenseIndex.open(
            store,
            path=DenseIndex.path_for(root, domain=manifest.domain, scope_id=manifest.scope_id, generation_id=manifest.generation_id),
            provider=provider,
        )
        all_patterns = {
            pattern.pattern_id: pattern
            for hint in ("general", "mapping", "three_hop_mapping")
            for pattern in adapter.allowed_graph_patterns(hint)
        }
        graph_engine = GraphSearchEngine(
            CatalogNeighborReader(store),
            allowed_pattern_ids=frozenset(all_patterns),
        )

        for record in queries:
            started = time.monotonic()
            query_id = str(record["query_id"])
            query = str(record["query"])
            per_channel: dict[str, list[str]] = {"exact": [], "lexical": [], "dense": [], "graph": []}
            predicted_paths: list[list[str]] = []
            errors: list[str] = []
            try:
                identifiers = adapter.parse_identifiers(query)
                exact_hits = []
                for identifier in identifiers:
                    exact_hits.extend(exact.lookup(identifier, scope=scope, snapshot=snapshot, top_k=config.channels.exact_top_k))
                exact_hits.sort(key=lambda hit: (int(hit.metadata.get("rank", 1)), str(hit.metadata.get("object_uid", ""))))
                per_channel["exact"] = _dedupe(
                    str(hit.metadata["object_uid"])
                    for hit in exact_hits
                    if _object_hit_allowed(store, policy, scope, hit)
                )

                for hit in lexical.search(query, scope=scope, snapshot=snapshot, top_k=config.channels.lexical_top_k):
                    try:
                        lexical.hydrate(hit, scope=scope, snapshot=snapshot, policy=policy)
                    except PermissionError:
                        continue
                    per_channel["lexical"].append(str(hit.metadata["object_uid"]))
                per_channel["lexical"] = _dedupe(per_channel["lexical"])

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
                        candidate = dense.candidate_for_hit(hit, scope=scope, snapshot=snapshot, policy=policy)
                    except PermissionError:
                        continue
                    per_channel["dense"].append(candidate.object_uid)
                per_channel["dense"] = _dedupe(per_channel["dense"])

                plan = planner.plan(
                    query,
                    authorized_seed_ids=per_channel["exact"],
                    max_graph_hops=min(3, config.graph.max_hops_mapping),
                    top_k=12,
                    lexical_enabled=True,
                    dense_enabled=True,
                )
                if plan.graph_enabled:
                    for pattern_id in plan.pattern_ids:
                        pattern = all_patterns[pattern_id]
                        result = graph_engine.search(
                            manifest=manifest,
                            pattern=pattern,
                            authorized_seed_ids=plan.authorized_seed_ids,
                            scope=scope,
                            snapshot=snapshot,
                            policy=policy,
                            deadline=time.monotonic() + config.timeouts.channel_seconds,
                            max_hops=plan.bounds.max_graph_hops,
                        )
                        for path in result.paths:
                            predicted_paths.append(list(path.ordered_node_uids))
                            per_channel["graph"].append(path.ordered_node_uids[-1])
                    per_channel["graph"] = _dedupe(per_channel["graph"])
            except Exception as exc:
                errors.append(type(exc).__name__)

            rankings = {
                "R1": list(per_channel["dense"]),
                "R2": list(per_channel["lexical"]),
                "R3": _rrf((per_channel["dense"], per_channel["lexical"])),
                "R4": _rrf((per_channel["dense"], per_channel["lexical"], per_channel["exact"])),
                "R5": _rrf((per_channel["dense"], per_channel["lexical"], per_channel["exact"], per_channel["graph"])),
            }
            predictions.append(
                {
                    "query_id": query_id,
                    "query": query,
                    "execution_status": "failed" if errors else "ok",
                    "execution_errors": errors,
                    "latency_ms": max(0.0, (time.monotonic() - started) * 1000.0),
                    "channel_rankings": per_channel,
                    "rankings": rankings,
                    "predicted_paths": predicted_paths,
                    "R6_status": "not_run",
                    "R6_reason": "fixture configuration has no explicit reranker provider; R6 quality is not fabricated",
                    "C1_status": "not_run",
                    "C1_reason": "context comparison requires the unavailable R6/final answer evaluation stage",
                }
            )
    return predictions, grouping_by_id, ingest_report


def _aggregate(results: Sequence[MetricResult], *, reason: str) -> MetricResult:
    ok = [item for item in results if item.status == MetricStatus.OK and item.value is not None]
    if not ok:
        statuses = {item.status for item in results}
        status = MetricStatus.NOT_APPLICABLE if statuses == {MetricStatus.NOT_APPLICABLE} else MetricStatus.NOT_RUN
        return MetricResult(status=status, reason=reason, support_count=0, annotation_coverage=0.0, value=None)
    return MetricResult(
        status=MetricStatus.OK,
        support_count=len(ok),
        annotation_coverage=len(ok) / len(results) if results else 0.0,
        value=sum(float(item.value) for item in ok) / len(ok),
    )


def _evaluate_predictions(predictions: list[dict[str, Any]], grouping_by_id: Mapping[str, QueryGrouping]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    # Evaluation-only labels are loaded only after every prediction is frozen.
    qrels_payload = json.loads(QRELS_PATH.read_text(encoding="utf-8"))
    qrels = qrels_payload.get("qrels", {})
    path_payload = json.loads(PATH_ANNOTATIONS.read_text(encoding="utf-8"))
    paths_by_query: dict[str, list[list[str]]] = {}
    for item in path_payload.get("paths", []):
        paths_by_query.setdefault(str(item["query_id"]), []).append(list(item["ordered_object_uids"]))

    metrics_by_ablation: dict[str, dict[str, list[MetricResult]]] = {
        name: {metric: [] for metric in ("hit@1", "hit@5", "recall@10", "mrr@10", "ndcg@10", "complete_path")}
        for name in ("R1", "R2", "R3", "R4", "R5")
    }
    recall10_by_query: dict[str, dict[str, float | None]] = {}

    for record in predictions:
        query_id = record["query_id"]
        labels = list(qrels.get(query_id, []))
        record["evaluation"] = {}
        recall10_by_query[query_id] = {}
        for name in ("R1", "R2", "R3", "R4", "R5"):
            ranking = record["rankings"][name]
            values = {
                "hit@1": hit_at_k(ranking, labels, 1),
                "hit@5": hit_at_k(ranking, labels, 5),
                "recall@10": recall_at_k(ranking, labels, 10),
                "mrr@10": mrr_at_k(ranking, labels, 10),
                "ndcg@10": ndcg_at_k(ranking, {item: 1.0 for item in labels}, 10),
                "complete_path": complete_path_hit(
                    record["predicted_paths"] if name == "R5" else (),
                    paths_by_query.get(query_id, ()),
                ),
            }
            record["evaluation"][name] = {key: value.model_dump(mode="json") for key, value in values.items()}
            recall10_by_query[query_id][name] = values["recall@10"].value
            for key, value in values.items():
                metrics_by_ablation[name][key].append(value)
        record["evaluation"]["evidence_document_recall@10"] = MetricResult(
            status=MetricStatus.NOT_APPLICABLE,
            reason="fixture supplies target-object qrels but no separate evidence-document labels",
            support_count=0,
            annotation_coverage=0.0,
            value=None,
        ).model_dump(mode="json")

    aggregate: dict[str, Any] = {}
    for name, metric_map in metrics_by_ablation.items():
        aggregate[name] = {
            metric: _aggregate(values, reason=f"no applicable {metric} annotations").model_dump(mode="json")
            for metric, values in metric_map.items()
        }

    unavailable = MetricResult(
        status=MetricStatus.NOT_RUN,
        reason="fixture has no configured final reranker provider",
        support_count=0,
        annotation_coverage=0.0,
        value=None,
    ).model_dump(mode="json")
    aggregate["R6"] = {metric: unavailable for metric in ("hit@1", "hit@5", "recall@10", "mrr@10", "ndcg@10", "complete_path")}
    aggregate["C1-basic"] = {"context_quality": MetricResult(status=MetricStatus.NOT_RUN, reason="no answer/generator evaluation configured", support_count=0, annotation_coverage=0.0, value=None).model_dump(mode="json")}
    aggregate["C1-structured"] = aggregate["C1-basic"]
    aggregate["L0"] = {
        "object_recall@10": MetricResult(
            status=MetricStatus.NOT_COMPARABLE,
            reason="L0 canonical object mapping is unavailable for the fixture comparator",
            support_count=0,
            annotation_coverage=0.0,
            value=None,
        ).model_dump(mode="json")
    }

    # Preregistered paired cluster bootstrap. R6-vs-R5 is unavailable; R5-vs-R4
    # can be computed mechanically, but this tiny fixture normally remains inconclusive.
    clustered: dict[str, list[float]] = {}
    for query_id, values in recall10_by_query.items():
        if values.get("R5") is None or values.get("R4") is None:
            continue
        group = grouping_by_id[query_id].near_duplicate_family
        clustered.setdefault(group, []).append(float(values["R5"]) - float(values["R4"]))
    interval = paired_cluster_bootstrap(clustered)
    if interval is None:
        graph_gain = MetricResult(
            status=MetricStatus.INCONCLUSIVE,
            reason="mapping-subset graph gain has fewer than two independent query-family clusters",
            support_count=0,
            annotation_coverage=0.0,
            value=None,
        )
    elif interval.lower_95 > 0.0:
        graph_gain = MetricResult(status=MetricStatus.OK, support_count=interval.cluster_count, annotation_coverage=1.0, value=interval.mean)
    else:
        graph_gain = MetricResult(
            status=MetricStatus.INCONCLUSIVE,
            reason=f"graph-gain lower 95% bound {interval.lower_95:.6f} is not greater than zero",
            support_count=interval.cluster_count,
            annotation_coverage=1.0,
            value=None,
        )
    aggregate["gates"] = {
        "R6_vs_R5_recall10_noninferiority": MetricResult(
            status=MetricStatus.NOT_RUN,
            reason="R6 unavailable without an explicit reranker provider/model",
            support_count=0,
            annotation_coverage=0.0,
            value=None,
        ).model_dump(mode="json"),
        "R5_vs_R4_graph_gain": graph_gain.model_dump(mode="json"),
        "real_quality_promotion": MetricResult(
            status=MetricStatus.NOT_RUN,
            reason="synthetic fixture establishes mechanics only; real held-out quality data/model gates were not run",
            support_count=0,
            annotation_coverage=0.0,
            value=None,
        ).model_dump(mode="json"),
    }
    return aggregate, predictions


def _report_files(
    *,
    config_path: Path,
    output: Path,
    config: AdvancedRagConfig,
    predictions: list[dict[str, Any]],
    grouping_by_id: Mapping[str, QueryGrouping],
    ingest_report: Mapping[str, Any],
    retrieval_metrics: Mapping[str, Any],
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    config_payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    _atomic_text(output / "config.snapshot.yaml", yaml.safe_dump(config_payload, sort_keys=True))
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
    corpus_payload = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    _write_json(output / "corpus.manifest.snapshot.json", {"sha256": _sha256(CORPUS_MANIFEST), "manifest": corpus_payload, "ingest_report": dict(ingest_report)})
    split = grouped_split(grouping_by_id.values())
    _write_json(output / "split.manifest.json", split.as_dict())
    _atomic_text(
        output / "per_query.jsonl",
        "".join(json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n" for item in predictions),
    )
    _write_json(output / "retrieval_metrics.json", retrieval_metrics)
    latency = [float(item["latency_ms"]) for item in predictions]
    _write_json(
        output / "latency_metrics.json",
        {
            "status": "ok" if latency else "not_run",
            "sample_count": len(latency),
            "concurrency": 1,
            "cache_state": "fixture-local-persistent-index-reopen",
            "mean_ms": sum(latency) / len(latency) if latency else None,
            "max_ms": max(latency) if latency else None,
            "throughput_reported": False,
        },
    )
    _write_json(
        output / "answer_metrics.json",
        {
            "answer_quality": MetricResult(status=MetricStatus.NOT_RUN, reason="retrieval evaluation does not invoke a generator", support_count=0, annotation_coverage=0.0, value=None).model_dump(mode="json"),
            "citation_validity": MetricResult(status=MetricStatus.NOT_RUN, reason="retrieval-only runner does not pack/generate response citations", support_count=0, annotation_coverage=0.0, value=None).model_dump(mode="json"),
            "citation_support": MetricResult(status=MetricStatus.NOT_RUN, reason="no independent answer/citation support judgments configured", support_count=0, annotation_coverage=0.0, value=None).model_dump(mode="json"),
        },
    )
    specs = native_ablation_matrix()
    validate_fair_matrix(specs)
    with (output / "ablation_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "description", "status", "recall10", "top_k", "pre_rerank_limit", "context_budget"])
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
    report_lines = [
        "# Advanced fixture retrieval evaluation",
        "",
        "This report is a deterministic synthetic-fixture mechanics report, not a real-quality promotion claim.",
        "",
        f"- queries: {len(predictions)}",
        f"- active generation: {ingest_report.get('generation_id')}",
        f"- L0 comparator: {'comparable' if l0['canonical_object_mapping_available'] else 'not_comparable'}",
        "- R6 reranker: not_run (no explicit fixture reranker provider)",
        "- answer/generator/judge quality: not_run",
        "- authorization ablation: forbidden/not performed",
        "- throughput claim: none (sequential fixture run)",
        "",
        "See retrieval_metrics.json, answer_metrics.json, latency_metrics.json, per_query.jsonl and ablation_summary.csv for machine-readable details.",
    ]
    _atomic_text(output / "report.md", "\n".join(report_lines) + "\n")


def run_retrieval_evaluation(*, config_path: Path, output: Path) -> dict[str, Any]:
    config = load_advanced_rag_config(config_path)
    if config.profile != "fixture":
        raise RuntimeError("the offline native evaluation command currently requires the deterministic fixture profile")
    # The ingest CLI intentionally accepts its selected config path. Store it on a
    # local validated copy only for this runner; no model is given qrels/answers.
    object.__setattr__(config, "config_path", str(config_path))
    predictions, grouping_by_id, ingest_report = _predict_fixture_queries(config)
    retrieval_metrics, predictions = _evaluate_predictions(predictions, grouping_by_id)
    _report_files(
        config_path=config_path,
        output=output,
        config=config,
        predictions=predictions,
        grouping_by_id=grouping_by_id,
        ingest_report=ingest_report,
        retrieval_metrics=retrieval_metrics,
    )
    return {
        "schema_version": "advanced-retrieval-eval-report-v1",
        "output": str(output),
        "queries": len(predictions),
        "real_quality": "not_run",
        "network_used": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic advanced retrieval evaluation")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_retrieval_evaluation(config_path=args.config, output=args.output)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
