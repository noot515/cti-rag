"""Minimal fail-closed serving helpers used to enforce policy before side effects."""
from __future__ import annotations
from cti_rag.contracts import CandidateBudget, PolicyLabels, SnapshotManifestRef, TemporalRequest
from cti_rag.ports.capabilities import ChannelResult, ChannelStatus, missing_capabilities
from cti_rag.ports.models import ModelRequest
from cti_rag.ports.policy import AuthenticatedPrincipal, ClientScopeRequest, PolicyDenied
from cti_rag.ports.search import SearchRequest, SearchKind

async def authorized_search(*,policy,principal:AuthenticatedPrincipal,client_scope:ClientScopeRequest,backend,query:str,kind:SearchKind,temporal:TemporalRequest,budget:CandidateBudget,snapshot:SnapshotManifestRef|None=None,required_filters=frozenset()):
    try:
        scope=policy.authorize(principal,client_scope)
    except Exception as exc:
        return ChannelResult(ChannelStatus.REJECTED,reason=f"policy:{type(exc).__name__}")
    if backend.capabilities.requires_snapshot and snapshot is None:
        return ChannelResult(ChannelStatus.REJECTED,reason="backend requires a pinned snapshot")
    mandatory=set(required_filters)|{"tenant","domain","access_label"}
    if scope.source_ids: mandatory.add("source")
    if temporal.mode.value != "current": mandatory.add("temporal")
    missing=missing_capabilities(backend.capabilities,frozenset(mandatory),temporal.mode,snapshot is not None)
    if missing: return ChannelResult(ChannelStatus.REJECTED,reason="unsupported mandatory capabilities: "+",".join(missing))
    request=SearchRequest(query=query,kind=kind,scope=scope,temporal=temporal,budget=budget,snapshot=snapshot,required_filters=frozenset(mandatory))
    return await backend.search(request)

async def authorized_model_call(*,policy,scope,model,operation,inputs,labels:PolicyLabels,destination):
    try:
        policy.authorize_model(scope,labels,operation.value,destination)
    except Exception as exc:
        raise PolicyDenied(f"model dispatch denied: {type(exc).__name__}") from exc
    return await model.invoke(ModelRequest(operation=operation,inputs=tuple(inputs),scope=scope,labels=labels,destination=destination))
