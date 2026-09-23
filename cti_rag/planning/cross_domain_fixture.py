"""Deterministic incident/network/abnormal-return cross-domain fixture."""
from __future__ import annotations
from datetime import datetime,timezone
from cti_rag.contracts import JsonPointerLocator,ProvenanceRef,TemporalMode,TemporalRequest,namespaced_uid
from .cross_domain import (
    JoinEvidenceKind,JoinedCalculationTemplate,JoinedGraphTemplate,TypedEntityKey,TypedJoinRecord,TypedJoinTemplate,
)
from .models import EvidenceObligation,PlanBudget,PlanNode,PlanOperation,QueryFeatures,QueryIntent,QueryPlan,Subquestion
from .validator import validate_plan

EVENT_DATE="2026-01-09"
EVENT_TIME="2026-01-09T20:00:00Z"
PUBLIC_CUTOFF="2026-01-10T00:30:00Z"
ISSUER=TypedEntityKey("cik","legal-entity","0000123456")
NETWORK_PREFIX=TypedEntityKey("cidr","prefix","203.0.113.0/24")
SECURITY=TypedEntityKey("security","security","SEC-EXAMPLE")
BENCHMARK_SECURITY="SEC-BENCH"

def _dt(v):return datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(timezone.utc)
def _rev(label):return namespaced_uid("rev","cross-domain.fixture",{"label":label})

ISSUER_NETWORK_TEMPLATE=TypedJoinTemplate("issuer-network-at-event","observed_network_association","cik","legal-entity","cidr","prefix",True)
ISSUER_SECURITY_TEMPLATE=TypedJoinTemplate("issuer-security-at-event","issued_security","cik","legal-entity","security","security",True)
NETWORK_GRAPH_TEMPLATE=JoinedGraphTemplate("joined-network-announcement","network-join","network-relations",("announced_by",),1)
RETURN_CALC_TEMPLATE=JoinedCalculationTemplate("joined-abnormal-return","security-join","event-study")

def incident_join_records(*,ambiguous_security=False,time_incompatible_network=False,suggestion_only_network=False,missing_price_security=False):
    network_valid_from=_dt("2025-01-01T00:00:00Z") if time_incompatible_network else _dt("2026-01-05T00:00:00Z")
    network_valid_to=_dt("2025-12-31T00:00:00Z") if time_incompatible_network else _dt("2026-01-11T00:00:00Z")
    network_kind=JoinEvidenceKind.GRAPH_SUGGESTION if suggestion_only_network else JoinEvidenceKind.CONFIRMED_RELATION
    rows=[
      TypedJoinRecord(ISSUER,"observed_network_association",NETWORK_PREFIX,"incident-network-observation-fixture",(ProvenanceRef(_rev("issuer-network"),JsonPointerLocator("/observed_network_resources/0")),),network_kind,_dt("2026-01-05T12:10:00Z"),network_valid_from,network_valid_to,domains=("quant","networking")),
      TypedJoinRecord(ISSUER,"observed_network_association",TypedEntityKey("cidr","prefix","198.51.100.0/24"),"graph-suggestion-fixture",(ProvenanceRef(_rev("network-suggestion"),JsonPointerLocator("/suggested_prefix")),),JoinEvidenceKind.GRAPH_SUGGESTION,_dt("2026-01-05T12:11:00Z"),_dt("2026-01-01T00:00:00Z"),_dt("2026-01-11T00:00:00Z"),domains=("quant","networking")),
      TypedJoinRecord(ISSUER,"issued_security",TypedEntityKey("security","security","SEC-NO-PRICE") if missing_price_security else SECURITY,"security-master-fixture",(ProvenanceRef(_rev("issuer-security"),JsonPointerLocator("/security_id")),),JoinEvidenceKind.CONFIRMED_RELATION,_dt("2025-01-01T00:00:00Z"),_dt("2025-01-01T00:00:00Z"),None,domains=("quant",)),
    ]
    if ambiguous_security:
        rows.append(TypedJoinRecord(ISSUER,"issued_security",TypedEntityKey("security","security","SEC-ALT"),"security-master-conflict-fixture",(ProvenanceRef(_rev("issuer-security-alt"),JsonPointerLocator("/security_id")),),JoinEvidenceKind.CONFIRMED_RELATION,_dt("2025-01-01T00:00:00Z"),_dt("2025-01-01T00:00:00Z"),None,domains=("quant",)))
    return tuple(rows)

def incident_market_plan(scope,snapshot,temporal=None,budget=None):
    required={"quant","networking"}
    if not required.issubset(set(scope.domains)):raise ValueError("incident cross-domain fixture requires authorized quant and networking domains")
    temporal=temporal or TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso=PUBLIC_CUTOFF)
    budget=budget or PlanBudget(deadline_ms=5000,max_backend_calls=8,max_expansion_rounds=0,max_total_candidates=80,max_rerank_candidates=20,max_context_tokens=4000)
    subquestions=(
      Subquestion("incident","Retrieve the disclosed incident and legal entity."),
      Subquestion("network","Resolve source-backed network infrastructure and route observation."),
      Subquestion("return","Resolve the historical security and calculate the declared abnormal return statistic."),
    )
    constraints=(("valid_at",EVENT_TIME),)
    nodes=(
      PlanNode("issuer-exact",PlanOperation.EXACT,"0000123456","incident",1,("quant",),required=True),
      PlanNode("incident-disclosure",PlanOperation.LEXICAL,"fictitious cybersecurity incident","incident",10,("quant",),required=True),
      PlanNode("network-join",PlanOperation.JOIN,"resolve issuer to observed network resource","network",3,("quant","networking"),("issuer-exact",),required=True,template_id=ISSUER_NETWORK_TEMPLATE.template_id,constraints=constraints),
      PlanNode("security-join",PlanOperation.JOIN,"resolve issuer to historical security","return",3,("quant",),("issuer-exact",),required=True,template_id=ISSUER_SECURITY_TEMPLATE.template_id,constraints=constraints),
      PlanNode("network-route",PlanOperation.GRAPH,"source-backed route observation","network",10,("networking",),("network-join",),required=True,template_id=NETWORK_GRAPH_TEMPLATE.template_id),
      PlanNode("abnormal-return",PlanOperation.STRUCTURED,"declared abnormal return statistic","return",1,("quant",),("security-join",),required=True,template_id=RETURN_CALC_TEMPLATE.template_id),
    )
    obligations=tuple(EvidenceObligation(n.node_id,n.operation.value,n.query,True,n.subquestion_id) for n in nodes)
    features=QueryFeatures((("cik","legal-entity","0000123456"),),(EVENT_DATE,),("USD",))
    return validate_plan(QueryPlan("Incident, network infrastructure, and abnormal return","incident network abnormal return",QueryIntent.CROSS_DOMAIN,scope,snapshot,temporal,budget,features,nodes,obligations,(),(),subquestions))
