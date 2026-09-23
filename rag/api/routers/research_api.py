"""Typed evidence-only research retrieval endpoint. Answer generation remains a separate concern."""
from __future__ import annotations
from typing import Any,Optional
from fastapi import APIRouter,Depends,HTTPException,status
from pydantic import BaseModel,Field
from cti_rag.contracts import TemporalMode,TemporalRequest,locator_to_data
from cti_rag.ports import ClientScopeRequest
from rag.api.advanced_runtime import get_advanced_runtime
from rag.utils.auth_middleware import get_required_user

research=APIRouter(prefix="/research",tags=["research"])

class TemporalRequestModel(BaseModel):
    mode:str="current"
    cutoff_iso:Optional[str]=None
    snapshot_manifest_id:Optional[str]=None
class AdvancedRetrievalRequestModel(BaseModel):
    query:str=Field(min_length=1,max_length=20000)
    domains:list[str]=Field(min_length=1,max_length=8)
    source_ids:list[str]=Field(default_factory=list,max_length=64)
    temporal:TemporalRequestModel=Field(default_factory=TemporalRequestModel)
    response_mode:str="evidence"
    top_k:int=Field(default=10,ge=1,le=100)
    debug:bool=False
    web_search:bool=False
    retrieval_profile:str="interactive"
class GapModel(BaseModel):
    obligation:str
    reason:str
    subquestion_id:str
class ChannelDiagnosticModel(BaseModel):
    node_id:str
    operation:str
    status:str
    reason_code:Optional[str]=None
class PassageEvidenceModel(BaseModel):
    passage_uid:str
    revision_uid:str
    text:str
    locator:dict[str,Any]
    source_id:str
    origin_group:str
    epistemic_label:str
    available_at:Optional[str]=None
    unit:Optional[str]=None
    citation_valid:bool
    truncated:bool
    token_count:int
class ExactEvidenceModel(BaseModel):
    canonical_id:str
    object_type:str
    revision_uid:str
    source_id:str
    locator:dict[str,Any]
class StructuredFieldModel(BaseModel):
    name:str
    value:Any
    data_type:str
    unit:Optional[str]=None
class StructuredEvidenceModel(BaseModel):
    result_uid:str
    revision_uids:list[str]
    fields:list[StructuredFieldModel]
    dataset_snapshot:Optional[str]=None
    query_spec_hash:Optional[str]=None
    temporal_mode:Optional[str]=None
    calculation_version:Optional[str]=None
class AdvancedRetrievalResponseModel(BaseModel):
    schema_version:str
    request_id:str
    plan_id:str
    snapshot_manifest_id:str
    status:str
    exact:list[ExactEvidenceModel]
    structured:list[StructuredEvidenceModel]
    passages:list[PassageEvidenceModel]
    gaps:list[GapModel]
    diagnostics:list[ChannelDiagnosticModel]
    degraded:bool
    degradation_reasons:list[str]
    debug_trace:Optional[dict[str,Any]]=None

def _temporal(value:TemporalRequestModel):
    try:mode=TemporalMode(value.mode)
    except ValueError as exc:raise HTTPException(status_code=422,detail="unsupported temporal mode") from exc
    return TemporalRequest(mode,value.cutoff_iso,value.snapshot_manifest_id)

def _serialize(response):
    exact=[]
    for item in response.exact:
        records=getattr(item,"records",())
        for r in records:exact.append(ExactEvidenceModel(canonical_id=r.canonical_id,object_type=r.object_type,revision_uid=r.revision_uid,source_id=r.source_id,locator=__import__("json").loads(r.locator_json)))
    structured=[]
    for item in response.structured:
        rows=getattr(item,"items",()) if getattr(getattr(item,"status",None),"value",None)=="ok" else ()
        for r in rows:structured.append(StructuredEvidenceModel(result_uid=r.result_uid,revision_uids=list(r.revision_uids),fields=[StructuredFieldModel(name=f.name,value=f.value,data_type=f.data_type,unit=f.unit) for f in r.fields],dataset_snapshot=r.dataset_snapshot,query_spec_hash=r.query_spec_hash,temporal_mode=r.temporal_mode,calculation_version=r.calculation_version))
    passages=[PassageEvidenceModel(passage_uid=p.evidence.passage.passage_uid,revision_uid=p.evidence.passage.revision_uid,text=p.display_text,locator=locator_to_data(p.evidence.passage.provenance.locator),source_id=p.evidence.source_id,origin_group=p.evidence.origin_group,epistemic_label=p.evidence.epistemic_label,available_at=None if p.evidence.available_at is None else p.evidence.available_at.isoformat(),unit=p.evidence.unit,citation_valid=p.citation_valid,truncated=p.truncated,token_count=p.token_count) for p in response.passages]
    trace=None
    if response.trace is not None:trace={k:(v.isoformat() if hasattr(v,"isoformat") else v) for k,v in response.trace.__dict__.items()}
    return AdvancedRetrievalResponseModel(schema_version=response.schema_version,request_id=response.request_id,plan_id=response.plan_id,snapshot_manifest_id=response.snapshot.manifest_id,status=response.status.value,exact=exact,structured=structured,passages=passages,gaps=[GapModel(obligation=g.obligation,reason=g.reason,subquestion_id=g.subquestion_id) for g in response.gaps],diagnostics=[ChannelDiagnosticModel(**d.__dict__) for d in response.diagnostics],degraded=response.degraded,degradation_reasons=list(response.degradation_reasons),debug_trace=trace)

@research.post("/advanced-retrieval",response_model=AdvancedRetrievalResponseModel)
async def advanced_retrieval(payload:AdvancedRetrievalRequestModel,current_user=Depends(get_required_user)):
    if payload.response_mode!="evidence":raise HTTPException(status_code=422,detail="advanced retrieval endpoint is evidence-only")
    if payload.web_search:raise HTTPException(status_code=422,detail="web overlay is not enabled on the offline advanced retrieval endpoint")
    binding=get_advanced_runtime()
    if binding is None:raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,detail="advanced retrieval runtime is disabled or not configured")
    principal=binding.principal_resolver(current_user)
    result=await binding.service.retrieve(query=payload.query,principal=principal,client_scope=ClientScopeRequest(tuple(payload.domains),tuple(payload.source_ids)),temporal=_temporal(payload.temporal),top_k=payload.top_k,debug=payload.debug)
    return _serialize(result)
