"""Validated query-DAG contracts for bounded retrieval execution."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple
from cti_rag.contracts import SnapshotManifestRef,TemporalRequest,namespaced_uid,sha256_hex
from cti_rag.ports import EffectiveScope

class PlanValidationError(ValueError): pass
class PlanOperation(str,Enum):
    EXACT="exact"; LEXICAL="lexical"; DENSE="dense"; GRAPH="graph"; STRUCTURED="structured"
class QueryIntent(str,Enum):
    EXACT="exact_lookup"; NUMERICAL="numerical"; EXPLANATION="explanation"; RELATION="relation"; CROSS_DOMAIN="cross_domain"

@dataclass(frozen=True)
class PlanBudget:
    deadline_ms:int=3000
    max_backend_calls:int=8
    max_expansion_rounds:int=1
    max_total_candidates:int=240
    max_rerank_candidates:int=60
    max_context_tokens:int=8000
    def __post_init__(self):
        values=(self.deadline_ms,self.max_backend_calls,self.max_total_candidates,self.max_rerank_candidates,self.max_context_tokens)
        if any(v<=0 for v in values) or self.max_expansion_rounds<0: raise PlanValidationError("invalid plan budget")

@dataclass(frozen=True)
class EvidenceObligation:
    obligation_id:str
    kind:str
    key:str
    required:bool=True
    subquestion_id:str="q0"

@dataclass(frozen=True)
class PlanGap:
    obligation:str
    reason:str
    subquestion_id:str="q0"

@dataclass(frozen=True)
class Subquestion:
    subquestion_id:str
    text:str
    def __post_init__(self):
        if not self.subquestion_id.strip() or not self.text.strip(): raise PlanValidationError("subquestion fields required")

@dataclass(frozen=True)
class PlanNode:
    node_id:str
    operation:PlanOperation
    query:str
    subquestion_id:str
    candidate_limit:int
    domains:Tuple[str,...]
    dependencies:Tuple[str,...]=()
    variant_key:str="base"
    required:bool=False
    def __post_init__(self):
        if not self.node_id.strip() or not self.query.strip() or not self.subquestion_id.strip(): raise PlanValidationError("plan node identity/query required")
        if self.candidate_limit<=0: raise PlanValidationError("plan node candidate limit must be positive")
        if not self.domains: raise PlanValidationError("plan node requires at least one domain")

@dataclass(frozen=True)
class QueryFeatures:
    identifiers:Tuple[Tuple[str,str,str],...]=()
    dates:Tuple[str,...]=()
    units:Tuple[str,...]=()

@dataclass(frozen=True)
class QueryPlan:
    original_query:str
    normalized_query:str
    intent:QueryIntent
    scope:EffectiveScope
    snapshot:SnapshotManifestRef
    temporal:TemporalRequest
    budget:PlanBudget
    features:QueryFeatures
    nodes:Tuple[PlanNode,...]
    obligations:Tuple[EvidenceObligation,...]=()
    gaps:Tuple[PlanGap,...]=()
    fallback_domains:Tuple[str,...]=()
    subquestions:Tuple[Subquestion,...]=()
    plan_version:str="query/2"
    plan_id:Optional[str]=None
    def __post_init__(self):
        if not self.original_query.strip() or not self.normalized_query.strip(): raise PlanValidationError("query text required")
        known={q.subquestion_id for q in self.subquestions}
        if self.subquestions and any(n.subquestion_id not in known for n in self.nodes): raise PlanValidationError("plan node references unknown subquestion")
        if self.plan_id is None:
            identity={"plan_version":self.plan_version,"query":self.normalized_query,"scope":scope_hash(self.scope),"snapshot":self.snapshot.manifest_id,"temporal":repr(self.temporal),"nodes":self.nodes,"obligations":self.obligations,"gaps":self.gaps,"budget":self.budget,"subquestions":self.subquestions}
            object.__setattr__(self,"plan_id",namespaced_uid("plan","query.plan",identity))
    @property
    def configuration_hash(self):
        return sha256_hex({"version":self.plan_version,"budget":self.budget,"nodes":self.nodes,"fallback_domains":self.fallback_domains})

def scope_hash(scope:EffectiveScope):
    return sha256_hex({"principal":scope.principal_id,"tenant":scope.tenant_id,"domains":scope.domains,"sources":scope.source_ids,"labels":[v.value for v in scope.access_labels],"processing":[v.value for v in scope.processing_classes],"policy_epoch":scope.policy_epoch,"private":scope.private_state_allowed})
