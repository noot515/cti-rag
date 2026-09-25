"""JSON loaders for versioned optimization grids and observations."""
from __future__ import annotations
import json
from pathlib import Path
from .models import MeasurementKind,OptimizationConfig,OptimizationObservation,OptimizationPlan

def load_grid(path):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    plan_data=data["plan"]
    plan=OptimizationPlan(
        plan_data["plan_id"],plan_data["baseline_config_id"],float(plan_data["ndcg_noninferiority_margin"]),
        float(plan_data["recall50_noninferiority_margin"]),float(plan_data["max_p95_latency_ms"]),
        None if plan_data.get("max_ram_mb") is None else float(plan_data["max_ram_mb"]),bool(plan_data.get("require_real_runtime_for_promotion",True)),
    )
    configs=tuple(OptimizationConfig(
        row["config_id"],int(row["passage_tokens"]),int(row["overlap_tokens"]),row["context_prefix_mode"],row["analyzer"],
        int(row["lexical_window"]),int(row["dense_window"]),int(row["ann_probe"]),int(row["rerank_candidates"]),int(row["context_tokens"]),
        int(row["graph_cap"]),int(row["routing_fallback_domains"]),bool(row["bulk_hydration"]),int(row["hydration_batch_size"]),
        tuple(row.get("dependencies",())),tuple(row.get("semantic_risks",()))
    ) for row in data["configs"])
    return plan,configs,data

def load_observations(path):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(OptimizationObservation(
        row["config_id"],row["split"],MeasurementKind(row["measurement_kind"]),float(row["ndcg_at_10"]),float(row["recall_at_50"]),
        float(row["ann_recall"]),float(row["graph_required_edge_recall"]),float(row["p50_latency_ms"]),float(row["p95_latency_ms"]),
        float(row["ram_peak_mb"]),int(row["index_bytes"]),int(row["backend_read_ops"]),bool(row["hard_gate_pass"]),
        bool(row["exact_structured_pass"]),bool(row["critical_slice_noninferior"]),row.get("notes","")
    ) for row in data["observations"])
