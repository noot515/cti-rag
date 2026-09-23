"""Typed reranking, packing, citation, and evidence-response contracts."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Tuple
from cti_rag.contracts import PassageHit,PolicyLabels,SnapshotManifestRef
from cti_rag.planning import FusedPassage,PlanGap

class EvidenceResponseStatus(str,Enum):
    COMPLETE="complete"
    PARTIAL="partial"
    INSUFFICIENT_EVIDENCE="insufficient_evidence"
    FAILED="failed"

@dataclass(frozen=True)
class EvidencePassage:
    fused:FusedPassage
    labels:PolicyLabels
    source_id:str
    origin_group:str
    snapshot_manifest_id:str
    available_at:Optional[datetime]=None
    epistemic_label:str="source_claim"
    unit:Optional[str]=None
    parent_uid:Optional[str]=None
    def __post_init__(self):
        if not self.source_id.strip() or not self.origin_group.strip() or not self.snapshot_manifest_id.strip():
            raise ValueError("evidence passage metadata fields required")
    @property
    def passage(self)->PassageHit:return self.fused.passage
    @property
    def subquestion_id(self)->str:return self.fused.subquestion_id

@dataclass(frozen=True)
class RerankedPassage:
    evidence:EvidencePassage
    base_rank:int
    rerank_rank:int
    score:float
    model_score:Optional[float]=None

@dataclass(frozen=True)
class RerankOutcome:
    passages:Tuple[RerankedPassage,...]
    degraded:bool=False
    reasons:Tuple[str,...]=()
    model_fingerprint:Optional[str]=None

@dataclass(frozen=True)
class PackedPassage:
    evidence:EvidencePassage
    display_text:str
    token_count:int
    truncated:bool
    citation_valid:bool
    parent_of:Optional[str]=None

@dataclass(frozen=True)
class ContextPack:
    passages:Tuple[PackedPassage,...]
    exact_obligations:Tuple[Any,...]
    structured_obligations:Tuple[Any,...]
    used_tokens:int
    token_budget:int
    missing_obligations:Tuple[PlanGap,...]
    origin_groups:Tuple[str,...]
    tokenizer_fingerprint:str
    graph_paths:Tuple[Any,...]=()

@dataclass(frozen=True)
class ChannelDiagnostic:
    node_id:str
    operation:str
    status:str
    reason_code:Optional[str]=None

@dataclass(frozen=True)
class RetrievalTrace:
    request_id:str
    query_digest:str
    scope_hash:str
    plan_id:str
    plan_configuration_hash:str
    snapshot_manifest_id:str
    policy_epoch:int
    reranker_fingerprint:Optional[str]
    tokenizer_fingerprint:str
    channel_statuses:Tuple[Tuple[str,str],...]
    started_at:datetime
    finished_at:datetime

@dataclass(frozen=True)
class AdvancedEvidenceResponse:
    schema_version:str
    request_id:str
    plan_id:str
    snapshot:SnapshotManifestRef
    status:EvidenceResponseStatus
    exact:Tuple[Any,...]
    structured:Tuple[Any,...]
    passages:Tuple[PackedPassage,...]
    gaps:Tuple[PlanGap,...]
    diagnostics:Tuple[ChannelDiagnostic,...]
    degraded:bool
    degradation_reasons:Tuple[str,...]
    trace:Optional[RetrievalTrace]=None
    graph_paths:Tuple[Any,...]=()
