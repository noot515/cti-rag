"""Fail-closed release, quality-confidence, rollback, and extraction gates."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from benchmark.advanced.metrics import BootstrapInterval, noninferiority_result, paired_cluster_bootstrap
from benchmark.advanced.matched_config import MatchedConfig, MatchedCorpusError, file_sha256, gate, resolve
from benchmark.advanced.report import MetricResult, MetricStatus
from packages.evidence.snapshot import SnapshotCatalog
from packages.evidence.store import EvidenceStore

class RollbackError(MatchedCorpusError):
    pass

def _unavailable(status: MetricStatus, reason: str) -> dict[str, Any]:
    return MetricResult(status=status, reason=reason, support_count=0, annotation_coverage=None, value=None).model_dump(mode="json")

def evaluate_ci_gate(interval: BootstrapInterval | None, *, kind: str, noninferiority_margin: float = -0.01) -> str:
    if kind == "noninferiority":
        return "pass" if noninferiority_result(interval, margin=noninferiority_margin).status == MetricStatus.OK else "inconclusive"
    if kind == "graph_gain":
        return "inconclusive" if interval is None else ("pass" if interval.lower_95 > 0.0 else "inconclusive")
    raise ValueError(kind)

def quality_evidence(config: MatchedConfig) -> dict[str, Any]:
    resamples = int(config.quality.get("bootstrap_resamples", 2000)); margin = float(config.quality.get("noninferiority_margin", -.01)); graph_bound = float(config.quality.get("graph_gain_lower_bound", 0.0))
    if resamples != 2000 or not math.isclose(margin, -.01, abs_tol=1e-12) or not math.isclose(graph_bound, 0.0, abs_tol=1e-12):
        raise MatchedCorpusError("Prompt 22 must preserve the Prompt 17 preregistered bootstrap and CI thresholds")
    judged = config.quality.get("judged_labels")
    if judged in {None, ""}:
        return {"matched_fixture_quality": _unavailable(MetricStatus.NOT_COMPARABLE, "matched recorded fixture has no comparable judged relevance labels"), "r6_vs_r5_recall_at_10_noninferiority": _unavailable(MetricStatus.NOT_RUN, "paired judged clusters unavailable"), "graph_mapping_gain": _unavailable(MetricStatus.NOT_RUN, "mapping-subset judged clusters unavailable"), "noninferiority_gate": "not_run", "graph_gain_gate": "not_run", "bootstrap_resamples": resamples, "noninferiority_margin": margin, "graph_gain_required_lower_bound_strictly_above": graph_bound, "quality_claim_from_fixture": False}
    path = resolve(Path(str(judged)))
    try: payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise MatchedCorpusError("judged quality evidence is unreadable") from exc
    r6, graph = payload.get("r6_vs_r5_recall_at_10_differences_by_cluster"), payload.get("graph_mapping_gain_differences_by_cluster")
    if not isinstance(r6, dict) or not isinstance(graph, dict):
        raise MatchedCorpusError("judged quality evidence lacks preregistered paired-cluster fields")
    r6_interval = paired_cluster_bootstrap(r6, resamples=resamples, seed=20260917); graph_interval = paired_cluster_bootstrap(graph, resamples=resamples, seed=20260917)
    r6_result = noninferiority_result(r6_interval, margin=margin); graph_gate = evaluate_ci_gate(graph_interval, kind="graph_gain")
    graph_result = (MetricResult(status=MetricStatus.OK, support_count=graph_interval.cluster_count, annotation_coverage=1.0, value=graph_interval.mean).model_dump(mode="json") if graph_gate == "pass" and graph_interval else _unavailable(MetricStatus.INCONCLUSIVE, "graph mapping gain lower 95% bound is not strictly above zero"))
    return {"matched_fixture_quality": _unavailable(MetricStatus.NOT_COMPARABLE, "matched fixture is mechanics-only; judged evidence is separate"), "judged_evidence": {"path": str(judged), "sha256": file_sha256(path)}, "r6_vs_r5_recall_at_10_noninferiority": r6_result.model_dump(mode="json"), "graph_mapping_gain": graph_result, "noninferiority_interval": None if r6_interval is None else r6_interval.__dict__, "graph_gain_interval": None if graph_interval is None else graph_interval.__dict__, "noninferiority_gate": "pass" if r6_result.status == MetricStatus.OK else "inconclusive", "graph_gain_gate": graph_gate, "bootstrap_resamples": resamples, "noninferiority_margin": margin, "graph_gain_required_lower_bound_strictly_above": graph_bound, "quality_claim_from_fixture": False}

def _decision(required: Mapping[str, str]) -> dict[str, Any]:
    failed = sorted(k for k, v in required.items() if v == "fail"); missing = sorted(k for k, v in required.items() if v in {"not_run", "not_comparable", "inconclusive"})
    ready = not failed and not missing and all(v == "pass" for v in required.values())
    return {"status": "ready_for_explicit_promotion" if ready else "hold", "blockers": [*(f"failed:{x}" for x in failed), *(f"unavailable:{x}" for x in missing)], "automatic_promotion": False}

def compute_readiness(*, matched_content: str, retrieval_parity: str, rollback_mechanics: str, release_evidence: Mapping[str, str], quality_gate: str = "not_run", graph_gain_gate: str = "not_run") -> dict[str, Any]:
    base = {"matched_content": gate(matched_content, "matched_content"), "retrieval_parity": gate(retrieval_parity, "retrieval_parity"), "rollback_mechanics": gate(rollback_mechanics, "rollback_mechanics"), "predecessor_correctness": gate(release_evidence["predecessor_correctness"], "predecessor_correctness"), "secret_handling": gate(release_evidence["secret_handling"], "secret_handling"), "freshness_lifecycle": gate(release_evidence["freshness_lifecycle"], "freshness_lifecycle")}
    mvp_b = {**base, "real_opencti": gate(release_evidence["real_opencti"], "real_opencti"), "real_milvus": gate(release_evidence["real_milvus"], "real_milvus"), "real_neo4j": gate(release_evidence["real_neo4j"], "real_neo4j"), "backend_isolation": gate(release_evidence["backend_isolation"], "backend_isolation")}
    mvp_c = {**mvp_b, "judged_quality": gate(release_evidence["judged_quality"], "judged_quality"), "quality_noninferiority": gate(quality_gate, "quality_noninferiority"), "graph_gain": gate(graph_gain_gate, "graph_gain"), "deployment_authorization": gate(release_evidence["deployment_authorization"], "deployment_authorization")}
    return {"MVP-A": {**_decision(base), "required_gates": base}, "MVP-B": {**_decision(mvp_b), "required_gates": mvp_b}, "MVP-C": {**_decision(mvp_c), "required_gates": mvp_c}, "overall": _decision(mvp_c)["status"], "advanced_default": "opt-in"}

def restore_retained_generation(store: EvidenceStore, *, domain: str, scope_id: str, corpus_id: str, target_generation_id: str) -> dict[str, Any]:
    catalog = SnapshotCatalog(store); before = catalog.active_generation(domain, scope_id, corpus_id); manifest = catalog.load_manifest(domain, scope_id, corpus_id, target_generation_id)
    if manifest is None or catalog.state(manifest) not in {"ready", "active"} or not catalog.all_verified(manifest):
        raise RollbackError("target retained generation is missing, failed, or unverified")
    catalog.activate(manifest); catalog.acknowledge(manifest); after = catalog.active_generation(domain, scope_id, corpus_id)
    if after is None or after["generation_id"] != target_generation_id:
        raise RollbackError("active generation pointer restore failed")
    return {"status": "pass", "previous_generation_id": None if before is None else before["generation_id"], "restored_generation_id": target_generation_id, "revocation_overlay_remains_live": True}

def enriched_experiment(path: Path | None) -> dict[str, Any]:
    if path is None: return {"status": "not_run", "reason": "no enriched OpenCTI coverage report configured", "combined_with_matched_comparison": False}
    resolved = resolve(path)
    if not resolved.is_file(): return {"status": "not_run", "reason": "configured enriched coverage report is unavailable", "path": str(path), "combined_with_matched_comparison": False}
    return {"status": "reported_separately", "path": str(path), "sha256": file_sha256(resolved), "combined_with_matched_comparison": False}

__all__ = ["RollbackError", "compute_readiness", "enriched_experiment", "evaluate_ci_gate", "quality_evidence", "restore_retained_generation"]
