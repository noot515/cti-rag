"""Measured optimization contracts for frozen tuning and holdout evaluation."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional,Tuple

class MeasurementKind(str,Enum):
    DETERMINISTIC_FIXTURE="deterministic_fixture"
    REAL_RUNTIME="real_runtime"

@dataclass(frozen=True)
class OptimizationConfig:
    config_id:str
    passage_tokens:int
    overlap_tokens:int
    context_prefix_mode:str
    analyzer:str
    lexical_window:int
    dense_window:int
    ann_probe:int
    rerank_candidates:int
    context_tokens:int
    graph_cap:int
    routing_fallback_domains:int
    bulk_hydration:bool
    hydration_batch_size:int
    dependencies:Tuple[str,...]=()
    semantic_risks:Tuple[str,...]=()
    def __post_init__(self):
        if not self.config_id.strip() or not self.context_prefix_mode.strip() or not self.analyzer.strip():raise ValueError("optimization config identity fields required")
        positive=(self.passage_tokens,self.lexical_window,self.dense_window,self.ann_probe,self.rerank_candidates,self.context_tokens,self.routing_fallback_domains,self.hydration_batch_size)
        if any(int(v)<=0 for v in positive) or self.overlap_tokens<0 or self.graph_cap<0:raise ValueError("optimization config bounds must be nonnegative/positive")
        if self.overlap_tokens>=self.passage_tokens:raise ValueError("passage overlap must be smaller than passage size")

@dataclass(frozen=True)
class OptimizationObservation:
    config_id:str
    split:str
    measurement_kind:MeasurementKind
    ndcg_at_10:float
    recall_at_50:float
    ann_recall:float
    graph_required_edge_recall:float
    p50_latency_ms:float
    p95_latency_ms:float
    ram_peak_mb:float
    index_bytes:int
    backend_read_ops:int
    ingestion_cost_units:float
    hard_gate_pass:bool
    exact_structured_pass:bool
    critical_slice_noninferior:bool
    notes:str=""
    def __post_init__(self):
        if not self.config_id.strip() or self.split not in ("tuning","holdout"):raise ValueError("optimization observation identity invalid")
        for value in (self.ndcg_at_10,self.recall_at_50,self.ann_recall,self.graph_required_edge_recall):
            if not 0<=float(value)<=1:raise ValueError("quality metrics must be in [0,1]")
        if min(self.p50_latency_ms,self.p95_latency_ms,self.ram_peak_mb,self.index_bytes,self.backend_read_ops,self.ingestion_cost_units)<0:raise ValueError("resource metrics cannot be negative")
        if self.p50_latency_ms>self.p95_latency_ms:raise ValueError("p50 latency cannot exceed p95")

@dataclass(frozen=True)
class OptimizationPlan:
    plan_id:str
    baseline_config_id:str
    ndcg_noninferiority_margin:float=.01
    recall50_noninferiority_margin:float=.01
    max_p95_latency_ms:float=5000.0
    max_ram_mb:Optional[float]=None
    ann_recall_noninferiority_margin:float=.01
    graph_recall_noninferiority_margin:float=.01
    require_real_runtime_for_promotion:bool=True
    def __post_init__(self):
        if not self.plan_id.strip() or not self.baseline_config_id.strip():raise ValueError("optimization plan identity required")
        if min(self.ndcg_noninferiority_margin,self.recall50_noninferiority_margin,self.ann_recall_noninferiority_margin,self.graph_recall_noninferiority_margin)<0 or self.max_p95_latency_ms<=0:raise ValueError("invalid optimization margins/budgets")

@dataclass(frozen=True)
class CandidateDecision:
    config_id:str
    eligible:bool
    reasons:Tuple[str,...]
    latency_delta_ms:float
    backend_read_delta:int
    index_bytes_delta:int
    ingestion_cost_delta:float

@dataclass(frozen=True)
class OptimizationDecision:
    plan_id:str
    tuning_choice:str
    production_choice:str
    status:str
    reason:str
    candidates:Tuple[CandidateDecision,...]
    holdout_evaluated:bool
