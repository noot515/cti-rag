"""Complete evidence-retrieval application service: admission -> snapshot -> plan -> retrieve -> rerank -> pack -> revalidate."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime,timezone
from cti_rag.context import AdvancedEvidenceResponse,ChannelDiagnostic,ContextBudget,EvidenceResponseStatus,capture_trace
from cti_rag.contracts import TemporalMode
from cti_rag.planning import PlanGap,PlanOperation,grouped_rrf

_FAILURE_STATUSES=frozenset(("timeout","unavailable","rejected"))
def _status_value(result):
    return getattr(getattr(result,"status",None),"value",None)
def _reason_code(result):
    status=_status_value(result)
    if status in ("timeout","unavailable","unsupported","rejected","empty","ok"):return status
    return "unknown"
def _available_operations(executor):
    ops=set()
    if executor.exact_index is not None:ops.add(PlanOperation.EXACT)
    if "lexical" in executor.search_ports:ops.add(PlanOperation.LEXICAL)
    if "dense" in executor.search_ports:ops.add(PlanOperation.DENSE)
    if executor.graph_port is not None:ops.add(PlanOperation.GRAPH)
    if executor.structured_port is not None:ops.add(PlanOperation.STRUCTURED)
    return ops

class AdvancedRetrievalService:
    def __init__(self,policy,catalog,planner,executor,hydrator,reranker,packer,context_budget:ContextBudget):
        self.policy=policy;self.catalog=catalog;self.planner=planner;self.executor=executor;self.hydrator=hydrator;self.reranker=reranker;self.packer=packer;self.context_budget=context_budget
    def _pin(self,scope,temporal):
        if temporal.mode==TemporalMode.HISTORICAL_SYSTEM_REPLAY:
            if hasattr(self.catalog,"pin_manifest"):return self.catalog.pin_manifest(temporal.snapshot_manifest_id,scope)
            manifest=self.catalog.get_manifest(temporal.snapshot_manifest_id)
            if manifest is None:raise KeyError(temporal.snapshot_manifest_id)
            return type("ResolvedSnapshot",(),{"manifest":manifest,"lease_id":None})()
        return self.catalog.pin_current(scope)
    async def retrieve(self,*,query,principal,client_scope,temporal,top_k=10,debug=False,requested_budget=None):
        started=datetime.now(timezone.utc);lease=None
        try:
            scope=self.policy.authorize(principal,client_scope);pinned=self._pin(scope,temporal);lease=getattr(pinned,"lease_id",None);snapshot=pinned.manifest.to_ref()
            plan=self.planner.compile(query,scope,snapshot,temporal,_available_operations(self.executor),requested_budget)
            execution=await self.executor.execute(plan);fusion=grouped_rrf(execution,top_k=plan.budget.max_rerank_candidates)
            hydrated,denied,invalid=self.hydrator.hydrate(fusion.passages,scope,snapshot)
            deadline=started+__import__("datetime").timedelta(milliseconds=plan.budget.deadline_ms)
            reranked=await self.reranker.rerank(query,hydrated,scope,deadline,plan.budget.max_rerank_candidates) if self.reranker is not None else __import__("cti_rag.context",fromlist=["RerankOutcome","RerankedPassage"]).RerankOutcome(tuple(__import__("cti_rag.context",fromlist=["RerankedPassage"]).RerankedPassage(v,i,i,v.fused.score,None) for i,v in enumerate(hydrated,1)))
            pack=await self.packer.pack(reranked,fusion,plan,self.context_budget)
            diagnostics=tuple(ChannelDiagnostic(item.node.node_id,item.node.operation.value,_status_value(item.result) or "typed",_reason_code(item.result)) for item in execution.nodes)
            gaps=list(pack.missing_obligations)
            if denied:gaps.append(PlanGap("authorization","candidate denied during canonical hydration"))
            if invalid:gaps.append(PlanGap("provenance","candidate failed canonical hydration"))
            # Final policy epoch/scope revalidation. It may narrow evidence after a long request.
            final_scope=self.policy.authorize(principal,client_scope)
            passages=tuple(p for p in pack.passages if p.evidence.labels.tenant_id in (final_scope.tenant_id,"public") and p.evidence.labels.access_label in final_scope.access_labels and p.evidence.labels.processing_class in final_scope.processing_classes)
            if len(passages)!=len(pack.passages):gaps.append(PlanGap("authorization","evidence revoked by final response policy"))
            exact=pack.exact_obligations;structured=pack.structured_obligations;graph_paths=pack.graph_paths
            evidence_count=len(passages)+len(graph_paths)+sum(1 for v in exact if _status_value(v)=="found")+sum(1 for v in structured if _status_value(v)=="ok")
            required_missing=any(g.obligation in ("exact","structured","required_evidence","citation","authorization") for g in gaps)
            failures=tuple(d for d in diagnostics if d.status in _FAILURE_STATUSES)
            successes=tuple(d for d in diagnostics if d.status in ("ok","empty","typed"))
            degraded=reranked.degraded or bool(denied or invalid)
            reasons=tuple(reranked.reasons)+(("canonical_hydration_filtered",) if denied or invalid else ())
            if evidence_count==0 and failures and not successes:status=EvidenceResponseStatus.FAILED
            elif evidence_count==0:status=EvidenceResponseStatus.INSUFFICIENT_EVIDENCE
            elif required_missing or gaps or degraded:status=EvidenceResponseStatus.PARTIAL
            else:status=EvidenceResponseStatus.COMPLETE
            trace=capture_trace(query=query,scope=scope,plan=plan,snapshot=snapshot,reranker_fingerprint=reranked.model_fingerprint,tokenizer_fingerprint=pack.tokenizer_fingerprint,channel_statuses=tuple((d.node_id,d.status) for d in diagnostics),started_at=started)
            return AdvancedEvidenceResponse("advanced-evidence/1",trace.request_id,plan.plan_id,snapshot,status,tuple(exact),tuple(structured),tuple(passages[:top_k]),tuple(gaps),diagnostics,degraded,reasons,trace if debug and final_scope.debug_traces_allowed else None,tuple(graph_paths[:top_k]))
        except Exception:
            raise
        finally:
            if lease is not None:
                try:self.catalog.release_lease(lease)
                except Exception:pass
