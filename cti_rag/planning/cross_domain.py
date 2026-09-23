"""Typed cross-domain joins, obligation coverage, and replay lineage.

The join runtime operates on namespace/type-qualified keys and source-backed
relationships. Display labels are never join keys, and graph suggestions cannot
satisfy a confirmed join obligation.
"""
from __future__ import annotations
import inspect
from dataclasses import dataclass
from datetime import datetime,timezone
from enum import Enum
from typing import Any,Callable,Mapping,Optional,Tuple

from cti_rag.contracts import AccessLabel,ProcessingClass,ProvenanceRef,StructuredResult,namespaced_uid,sha256_hex
from cti_rag.ports import ChannelResult,ChannelStatus,GraphRequest
from cti_rag.retrieval import ExactLookupResult,ExactLookupStatus
from .fusion import grouped_rrf
from .models import EvidenceObligation,PlanOperation,QueryPlan

class JoinEvidenceKind(str,Enum):
    CONFIRMED_RELATION="confirmed_relation"
    GRAPH_SUGGESTION="graph_suggestion"

class TypedJoinStatus(str,Enum):
    RESOLVED="resolved"
    AMBIGUOUS="ambiguous"
    MISSING="missing"
    TIME_INCOMPATIBLE="time_incompatible"
    SUGGESTION_ONLY="suggestion_only"
    REJECTED="rejected"

@dataclass(frozen=True)
class TypedEntityKey:
    namespace:str
    entity_type:str
    identifier:str
    def __post_init__(self):
        if not all(str(v).strip() for v in (self.namespace,self.entity_type,self.identifier)):raise ValueError("typed entity key fields required")
    @property
    def identity(self):return (self.namespace,self.entity_type,self.identifier)

@dataclass(frozen=True)
class TypedJoinRecord:
    left:TypedEntityKey
    relation:str
    right:TypedEntityKey
    source_id:str
    support:Tuple[ProvenanceRef,...]
    evidence_kind:JoinEvidenceKind=JoinEvidenceKind.CONFIRMED_RELATION
    available_at:Optional[datetime]=None
    valid_from:Optional[datetime]=None
    valid_to:Optional[datetime]=None
    tenant_id:str="public"
    access_label:AccessLabel=AccessLabel.PUBLIC
    processing_class:ProcessingClass=ProcessingClass.LOCAL_ONLY
    domains:Tuple[str,...]=()
    system_manifest_id:Optional[str]=None
    def __post_init__(self):
        if not self.relation.strip() or not self.source_id.strip() or not self.support:raise ValueError("typed join record requires relation/source/support")
        for value in (self.available_at,self.valid_from,self.valid_to):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):raise ValueError("typed join timestamps must be timezone-aware")
        if self.valid_from is not None and self.valid_to is not None and self.valid_to<=self.valid_from:raise ValueError("typed join validity interval reversed")
        if not self.domains:raise ValueError("typed join record requires source domains")

@dataclass(frozen=True)
class TypedJoinTemplate:
    template_id:str
    relation:str
    left_namespace:str
    left_type:str
    right_namespace:str
    right_type:str
    require_valid_at:bool=True
    def __post_init__(self):
        if not all(str(v).strip() for v in (self.template_id,self.relation,self.left_namespace,self.left_type,self.right_namespace,self.right_type)):raise ValueError("typed join template fields required")

@dataclass(frozen=True)
class TypedJoinResult:
    join_id:str
    status:TypedJoinStatus
    template_id:str
    left:Optional[TypedEntityKey]
    relation:str
    selected:Optional[TypedEntityKey]=None
    candidates:Tuple[TypedEntityKey,...]=()
    support:Tuple[ProvenanceRef,...]=()
    suggestions:Tuple[TypedEntityKey,...]=()
    source_ids:Tuple[str,...]=()
    reason:Optional[str]=None
    def __post_init__(self):
        if self.status==TypedJoinStatus.RESOLVED and self.selected is None:raise ValueError("resolved typed join requires selected key")
        if self.status!=TypedJoinStatus.RESOLVED and self.selected is not None:raise ValueError("unresolved typed join cannot expose selected key")

def _dt(value):
    if value is None:return None
    if isinstance(value,datetime):
        if value.tzinfo is None or value.utcoffset() is None:raise ValueError("join time requires timezone")
        return value.astimezone(timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(timezone.utc)

def _status_value(value):
    return getattr(getattr(value,"status",None),"value",str(getattr(value,"status","unknown")))

def _key_from_result(value):
    if isinstance(value,ExactLookupResult) and value.status==ExactLookupStatus.FOUND and len(value.records)==1:
        r=value.records[0];return TypedEntityKey(r.namespace,r.object_type,r.canonical_id)
    if isinstance(value,TypedJoinResult) and value.status==TypedJoinStatus.RESOLVED:
        return value.selected
    return None

class TypedJoinPort:
    """In-memory reference join boundary for validated typed relationship records."""
    def __init__(self,templates,records):
        self.templates={x.template_id:x for x in templates};self.records=tuple(records)
    @staticmethod
    def _policy(record,scope):
        return record.tenant_id in (scope.tenant_id,"public") and record.access_label in scope.access_labels and record.processing_class in scope.processing_classes and (not scope.source_ids or record.source_id in scope.source_ids) and set(record.domains).issubset(set(scope.domains))
    @staticmethod
    def _availability(record,temporal):
        if temporal.mode.value=="historical_system_replay":
            return record.system_manifest_id==temporal.snapshot_manifest_id
        point=datetime.now(timezone.utc)
        if temporal.mode.value=="historical_public":
            if not temporal.cutoff_iso or record.available_at is None:return False
            point=_dt(temporal.cutoff_iso)
        return record.available_at is None or record.available_at<=point
    async def run(self,node,scope,snapshot,temporal,prior,deadline,cancel_token):
        template=self.templates.get(node.template_id or "")
        if template is None:return TypedJoinResult(namespaced_uid("join","typed.join",{"node":node.node_id,"template":node.template_id}),TypedJoinStatus.REJECTED,node.template_id or "",None,"",reason="unknown typed join template")
        left=None
        for dep in node.dependencies:
            left=_key_from_result(prior.get(dep))
            if left is not None:break
        if left is None:
            return TypedJoinResult(namespaced_uid("join","typed.join",{"node":node.node_id,"template":template.template_id,"reason":"missing-left"}),TypedJoinStatus.MISSING,template.template_id,None,template.relation,reason="no resolved typed left key from dependencies")
        if left.namespace!=template.left_namespace or left.entity_type!=template.left_type:
            return TypedJoinResult(namespaced_uid("join","typed.join",{"node":node.node_id,"left":left.identity}),TypedJoinStatus.REJECTED,template.template_id,left,template.relation,reason="left key namespace/type mismatch")
        constraints=dict(node.constraints);valid_at=_dt(constraints.get("valid_at")) if constraints.get("valid_at") else None
        if template.require_valid_at and valid_at is None:
            return TypedJoinResult(namespaced_uid("join","typed.join",{"node":node.node_id,"left":left.identity,"reason":"missing-valid-at"}),TypedJoinStatus.REJECTED,template.template_id,left,template.relation,reason="typed join requires explicit valid_at")
        typed=[r for r in self.records if r.left==left and r.relation==template.relation and r.right.namespace==template.right_namespace and r.right.entity_type==template.right_type and self._policy(r,scope) and self._availability(r,temporal)]
        suggestions=tuple(sorted({r.right.identity:r.right for r in typed if r.evidence_kind==JoinEvidenceKind.GRAPH_SUGGESTION}.values(),key=lambda x:x.identity))
        confirmed=[r for r in typed if r.evidence_kind==JoinEvidenceKind.CONFIRMED_RELATION]
        time_eligible=[]
        for r in confirmed:
            if valid_at is not None and ((r.valid_from is not None and r.valid_from>valid_at) or (r.valid_to is not None and r.valid_to<=valid_at)):continue
            time_eligible.append(r)
        unique={r.right.identity:r for r in time_eligible}
        all_candidates=tuple(sorted((TypedEntityKey(*key) for key in unique),key=lambda x:x.identity))
        ident={"node":node.node_id,"template":template.template_id,"left":left.identity,"valid_at":valid_at,"snapshot":getattr(snapshot,"manifest_id",None),"candidates":tuple(x.identity for x in all_candidates),"suggestions":tuple(x.identity for x in suggestions)}
        join_id=namespaced_uid("join","typed.join",ident)
        if len(all_candidates)>1:
            support=tuple(p for r in unique.values() for p in r.support)
            return TypedJoinResult(join_id,TypedJoinStatus.AMBIGUOUS,template.template_id,left,template.relation,None,all_candidates,support,suggestions,tuple(sorted({r.source_id for r in unique.values()})),reason="multiple source-backed typed targets remain eligible")
        if len(all_candidates)==1:
            record=next(iter(unique.values()))
            return TypedJoinResult(join_id,TypedJoinStatus.RESOLVED,template.template_id,left,template.relation,record.right,all_candidates,record.support,suggestions,(record.source_id,))
        if confirmed:
            return TypedJoinResult(join_id,TypedJoinStatus.TIME_INCOMPATIBLE,template.template_id,left,template.relation,None,(),(),suggestions,(),reason="typed relation exists but no confirmed record is valid at requested time")
        if suggestions:
            return TypedJoinResult(join_id,TypedJoinStatus.SUGGESTION_ONLY,template.template_id,left,template.relation,None,(),(),suggestions,(),reason="only graph-derived suggestions are available; confirmed identity/relation not established")
        return TypedJoinResult(join_id,TypedJoinStatus.MISSING,template.template_id,left,template.relation,reason="no eligible typed relation")

@dataclass(frozen=True)
class JoinedGraphTemplate:
    template_id:str
    join_dependency:str
    graph_template_id:str
    relations:Tuple[str,...]
    max_hops:int=1

class JoinedGraphPort:
    """Adapter that seeds an existing GraphPort only from a resolved typed join."""
    def __init__(self,graph_port,templates):
        self.graph_port=graph_port;self.templates={x.template_id:x for x in templates}
    async def run(self,node,scope,snapshot,temporal,prior,deadline,cancel_token):
        template=self.templates.get(node.template_id or "")
        if template is None:return ChannelResult(ChannelStatus.REJECTED,reason="unknown joined graph template")
        joined=prior.get(template.join_dependency)
        if not isinstance(joined,TypedJoinResult) or joined.status!=TypedJoinStatus.RESOLVED:return ChannelResult(ChannelStatus.REJECTED,reason="joined graph requires resolved typed join")
        key=joined.selected
        resolution=getattr(self.graph_port,"resolution",None)
        if resolution is None:return ChannelResult(ChannelStatus.UNSUPPORTED,reason="graph entity resolution unavailable")
        entities=resolution.exact(key.namespace,key.entity_type,key.identifier)
        if not entities:return ChannelResult(ChannelStatus.EMPTY,reason="resolved typed key has no graph entity in pinned projection")
        seeds=tuple(e.entity_uid for e in entities)
        request=GraphRequest(seeds,template.relations,scope,temporal,template.max_hops,node.candidate_limit,snapshot,deadline,cancel_token,template.graph_template_id)
        return await self.graph_port.traverse(request)

@dataclass(frozen=True)
class JoinedCalculationTemplate:
    template_id:str
    join_dependency:str
    calculator_id:str

class JoinedCalculationPort:
    """Executes registered verified calculations only after a resolved typed join."""
    def __init__(self,templates,calculators:Mapping[str,Callable]):
        self.templates={x.template_id:x for x in templates};self.calculators=dict(calculators)
    async def run(self,node,scope,snapshot,temporal,prior,deadline,cancel_token):
        template=self.templates.get(node.template_id or "")
        if template is None:return ChannelResult(ChannelStatus.REJECTED,reason="unknown joined calculation template")
        joined=prior.get(template.join_dependency)
        if not isinstance(joined,TypedJoinResult) or joined.status!=TypedJoinStatus.RESOLVED:return ChannelResult(ChannelStatus.REJECTED,reason="calculation requires resolved typed join")
        calculator=self.calculators.get(template.calculator_id)
        if calculator is None:return ChannelResult(ChannelStatus.UNSUPPORTED,reason="calculation template is not registered")
        try:
            value=calculator(joined.selected,scope,snapshot,temporal)
            if inspect.isawaitable(value):value=await value
        except ValueError as exc:
            return ChannelResult(ChannelStatus.EMPTY,reason=f"calculation input missing: {exc}")
        if isinstance(value,ChannelResult):return value
        if isinstance(value,StructuredResult):return ChannelResult(ChannelStatus.OK,(value,))
        return ChannelResult(ChannelStatus.REJECTED,reason="calculator returned unsupported result type")

class CoverageStatus(str,Enum):
    SATISFIED="satisfied"
    PARTIAL="partial"
    MISSING="missing"
    FAILED="failed"

@dataclass(frozen=True)
class ObligationCoverage:
    obligation_id:str
    kind:str
    subquestion_id:str
    required:bool
    status:CoverageStatus
    citation_count:int
    reason:str=""

def citation_count(value)->int:
    if value is None:return 0
    if isinstance(value,ExactLookupResult):return len(value.records) if value.status==ExactLookupStatus.FOUND else 0
    if isinstance(value,TypedJoinResult):return len(value.support)
    if isinstance(value,ChannelResult):return sum(citation_count(x) for x in value.items) if value.status==ChannelStatus.OK else 0
    if hasattr(value,"provenances"):return len(getattr(value,"provenances") or ())
    if hasattr(value,"provenance"):return 1
    if isinstance(value,(tuple,list)):return sum(citation_count(x) for x in value)
    return 0

def _coverage_status(result):
    citations=citation_count(result)
    if isinstance(result,ExactLookupResult):
        if result.status==ExactLookupStatus.FOUND:return (CoverageStatus.SATISFIED if citations else CoverageStatus.PARTIAL,result.reason or "")
        if result.status in (ExactLookupStatus.NOT_FOUND,ExactLookupStatus.AMBIGUOUS):return (CoverageStatus.MISSING,result.reason or result.status.value)
        return (CoverageStatus.FAILED,result.reason or result.status.value)
    if isinstance(result,TypedJoinResult):
        if result.status==TypedJoinStatus.RESOLVED:return (CoverageStatus.SATISFIED if citations else CoverageStatus.PARTIAL,result.reason or "")
        if result.status in (TypedJoinStatus.AMBIGUOUS,TypedJoinStatus.TIME_INCOMPATIBLE,TypedJoinStatus.SUGGESTION_ONLY):return (CoverageStatus.PARTIAL,result.reason or result.status.value)
        if result.status==TypedJoinStatus.MISSING:return (CoverageStatus.MISSING,result.reason or result.status.value)
        return (CoverageStatus.FAILED,result.reason or result.status.value)
    if isinstance(result,ChannelResult):
        if result.status==ChannelStatus.OK:return (CoverageStatus.SATISFIED if citations else CoverageStatus.PARTIAL,result.reason or "")
        if result.status==ChannelStatus.EMPTY:return (CoverageStatus.MISSING,result.reason or "empty")
        return (CoverageStatus.FAILED,result.reason or result.status.value)
    return (CoverageStatus.FAILED,"unknown obligation result type")

def evaluate_obligation_coverage(plan:QueryPlan,execution)->Tuple[ObligationCoverage,...]:
    out=[]
    for obligation in plan.obligations:
        result=execution.result_for(obligation.obligation_id)
        status,reason=_coverage_status(result)
        out.append(ObligationCoverage(obligation.obligation_id,obligation.kind,obligation.subquestion_id,obligation.required,status,citation_count(result),reason))
    return tuple(out)

@dataclass(frozen=True)
class CrossDomainReplayTrace:
    trace_id:str
    plan_id:str
    plan_configuration_hash:str
    snapshot_manifest_id:str
    node_statuses:Tuple[Tuple[str,str,str],...]
    join_decisions:Tuple[Tuple[str,str,Optional[Tuple[str,str,str]]],...]
    calculation_lineage:Tuple[Tuple[str,str,Optional[str],Optional[str],Tuple[str,...]],...]

def build_replay_trace(plan,execution,coverage):
    node_statuses=[];joins=[];calculations=[]
    for item in execution.nodes:
        result=item.result;node_statuses.append((item.node.node_id,item.node.operation.value,_status_value(result)))
        if isinstance(result,TypedJoinResult):joins.append((item.node.node_id,result.status.value,None if result.selected is None else result.selected.identity))
        if isinstance(result,ChannelResult) and result.status==ChannelStatus.OK:
            for value in result.items:
                if isinstance(value,StructuredResult):calculations.append((item.node.node_id,value.result_uid,value.input_manifest,value.calculation_version,value.revision_uids))
    material={"plan":plan.plan_id,"config":plan.configuration_hash,"snapshot":plan.snapshot.manifest_id,"nodes":node_statuses,"joins":joins,"calculations":calculations,"coverage":coverage}
    return CrossDomainReplayTrace(namespaced_uid("trace","cross-domain.replay",material),plan.plan_id,plan.configuration_hash,plan.snapshot.manifest_id,tuple(node_statuses),tuple(joins),tuple(calculations))

@dataclass(frozen=True)
class CrossDomainOutcome:
    status:str
    execution:object
    fusion:object
    coverage:Tuple[ObligationCoverage,...]
    unresolved_joins:Tuple[TypedJoinResult,...]
    trace:CrossDomainReplayTrace
    claim_scope_note:str="Supported co-occurrence and association evidence does not by itself establish causal attribution or profitability."

class CrossDomainCoordinator:
    async def execute(self,plan,executor,top_k=20):
        execution=await executor.execute(plan);fusion=grouped_rrf(execution,top_k=top_k);coverage=evaluate_obligation_coverage(plan,execution)
        unresolved=tuple(item.result for item in execution.nodes if item.node.operation==PlanOperation.JOIN and isinstance(item.result,TypedJoinResult) and item.result.status!=TypedJoinStatus.RESOLVED)
        required=tuple(x for x in coverage if x.required)
        if required and all(x.status==CoverageStatus.SATISFIED for x in required):status="complete"
        elif any(x.status==CoverageStatus.SATISFIED for x in coverage):status="partial"
        else:status="insufficient_evidence"
        return CrossDomainOutcome(status,execution,fusion,coverage,unresolved,build_replay_trace(plan,execution,coverage))
