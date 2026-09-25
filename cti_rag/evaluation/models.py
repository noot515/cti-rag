"""Versioned evaluation contracts for multidomain retrieval/grounding experiments."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional,Tuple

class JudgmentStatus(str,Enum):
    HUMAN_REVIEWED="human_reviewed"
    MACHINE_GENERATED_UNREVIEWED="machine_generated_unreviewed"
    SYNTHETIC_CONTRACT="synthetic_contract"

class ModelExecutionKind(str,Enum):
    NONE="none"
    DETERMINISTIC_FAKE="deterministic_fake"
    REAL_MODEL="real_model"

@dataclass(frozen=True)
class EvaluationQuery:
    query_id:str
    domain:str
    text:str
    task_type:str
    source_family:str
    duplicate_group:str
    split:str
    temporal_bucket:str
    answerable:bool
    required_routes:Tuple[str,...]=()
    required_subquestions:Tuple[str,...]=()
    adversarial_tags:Tuple[str,...]=()
    locale:str="en-US"
    def __post_init__(self):
        required=(self.query_id,self.domain,self.text,self.task_type,self.source_family,self.duplicate_group,self.split,self.temporal_bucket,self.locale)
        if any(not str(v).strip() for v in required):raise ValueError("evaluation query identity fields required")

@dataclass(frozen=True)
class RelevanceJudgment:
    query_id:str
    status:JudgmentStatus
    relevance:Tuple[Tuple[str,int],...]
    expected_structured:Tuple[Tuple[str,str,str],...]=()
    expected_citations:Tuple[str,...]=()
    required_graph_edges:Tuple[str,...]=()
    reviewer_ids:Tuple[str,...]=()
    notes:Optional[str]=None
    def __post_init__(self):
        if not self.query_id.strip():raise ValueError("judgment query_id required")
        if any(int(grade)<0 for _uid,grade in self.relevance):raise ValueError("relevance grades must be nonnegative")
        if self.status==JudgmentStatus.HUMAN_REVIEWED and not self.reviewer_ids:raise ValueError("human-reviewed judgment requires reviewer provenance")

@dataclass(frozen=True)
class QueryOutcome:
    query_id:str
    returned_uids:Tuple[str,...]=()
    returned_origin_groups:Tuple[str,...]=()
    router_routes:Tuple[str,...]=()
    ann_ids:Tuple[str,...]=()
    exhaustive_ann_ids:Tuple[str,...]=()
    covered_subquestions:Tuple[str,...]=()
    covered_graph_edges:Tuple[str,...]=()
    structured_values:Tuple[Tuple[str,str,str],...]=()
    packed_uids:Tuple[str,...]=()
    citations:Tuple[Tuple[str,bool],...]=()
    answered:bool=False
    abstained:bool=False
    answer_error:bool=False
    latency_ms:float=0.0
    stage_latency_ms:Tuple[Tuple[str,float],...]=()
    ram_peak_mb:Optional[float]=None
    vram_peak_mb:Optional[float]=None
    backend_failure:bool=False
    policy_failure:bool=False
    temporal_failure:bool=False
    returned_source_families:Tuple[str,...]=()
    def __post_init__(self):
        if not self.query_id.strip() or self.latency_ms<0:raise ValueError("invalid query outcome")
        if self.returned_origin_groups and len(self.returned_origin_groups)!=len(self.returned_uids):
            raise ValueError("origin groups must align with returned_uids")

@dataclass(frozen=True)
class RunMetadata:
    baseline:str
    scope_hash:str
    snapshot_id:str
    candidate_budget:int
    resource_condition:str
    model_execution:ModelExecutionKind=ModelExecutionKind.NONE
    model_fingerprints:Tuple[str,...]=()
    provider_fingerprints:Tuple[str,...]=()
    config_fingerprint:str="evaluation/default"
    def __post_init__(self):
        if not self.baseline.strip() or not self.scope_hash.strip() or not self.snapshot_id.strip() or self.candidate_budget<=0 or not self.resource_condition.strip():
            raise ValueError("run metadata fields required")
        if self.model_execution==ModelExecutionKind.REAL_MODEL and not self.model_fingerprints:
            raise ValueError("real-model run requires model fingerprints")

@dataclass(frozen=True)
class EvaluationRun:
    metadata:RunMetadata
    outcomes:Tuple[QueryOutcome,...]

@dataclass(frozen=True)
class ExperimentConfig:
    experiment_id:str
    seed:int
    baselines:Tuple[str,...]
    scope_hash:str
    snapshot_id:str
    candidate_budget:int
    resource_condition:str
    recall_ks:Tuple[int,...]=(20,50,100)
    ndcg_k:int=10
    bootstrap_replicates:int=1000
    confidence:float=0.95
    min_conclusive_pairs:int=30
    ndcg_noninferiority_margin:float=0.01
    recall50_noninferiority_margin:float=0.01
    max_p95_latency_ms:float=5000.0
    max_ram_mb:Optional[float]=None
    max_vram_mb:Optional[float]=None
    def __post_init__(self):
        object.__setattr__(self,"seed",int(self.seed))
        object.__setattr__(self,"candidate_budget",int(self.candidate_budget))
        object.__setattr__(self,"recall_ks",tuple(int(v) for v in self.recall_ks))
        object.__setattr__(self,"ndcg_k",int(self.ndcg_k))
        object.__setattr__(self,"bootstrap_replicates",int(self.bootstrap_replicates))
        object.__setattr__(self,"confidence",float(self.confidence))
        object.__setattr__(self,"min_conclusive_pairs",int(self.min_conclusive_pairs))
        object.__setattr__(self,"ndcg_noninferiority_margin",float(self.ndcg_noninferiority_margin))
        object.__setattr__(self,"recall50_noninferiority_margin",float(self.recall50_noninferiority_margin))
        object.__setattr__(self,"max_p95_latency_ms",float(self.max_p95_latency_ms))
        object.__setattr__(self,"max_ram_mb",None if self.max_ram_mb is None else float(self.max_ram_mb))
        object.__setattr__(self,"max_vram_mb",None if self.max_vram_mb is None else float(self.max_vram_mb))
        if not self.experiment_id.strip() or not self.baselines or self.candidate_budget<=0:raise ValueError("invalid experiment config")
        if any(k<=0 for k in self.recall_ks) or self.ndcg_k<=0 or self.bootstrap_replicates<=0:raise ValueError("invalid metric configuration")
        if not 0<self.confidence<1 or self.min_conclusive_pairs<=0:raise ValueError("invalid inference configuration")
        if self.ndcg_noninferiority_margin<0 or self.recall50_noninferiority_margin<0 or self.max_p95_latency_ms<=0:raise ValueError("invalid promotion budgets")
