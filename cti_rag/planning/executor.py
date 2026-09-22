"""Bounded asynchronous DAG executor with typed statuses and cancellation propagation."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from typing import Any,Tuple
from cti_rag.contracts import CandidateBudget
from cti_rag.ports import ChannelResult,ChannelStatus,EffectiveScope,SearchKind,SearchRequest
from cti_rag.retrieval.models import ExactLookupRequest,ExactLookupResult,ExactLookupStatus
from .models import PlanGap,PlanNode,PlanOperation

@dataclass(frozen=True)
class NodeExecution:
    node:PlanNode
    result:Any
@dataclass(frozen=True)
class QueryExecution:
    plan_id:str
    nodes:Tuple[NodeExecution,...]
    gaps:Tuple[PlanGap,...]
    started_at:datetime
    finished_at:datetime
    def result_for(self,node_id):
        for item in self.nodes:
            if item.node.node_id==node_id:return item.result
        return None

class QueryExecutor:
    def __init__(self,search_ports=None,exact_index=None,graph_port=None,structured_port=None,max_concurrency=4):
        self.search_ports=search_ports or {}; self.exact_index=exact_index; self.graph_port=graph_port; self.structured_port=structured_port; self.max_concurrency=max_concurrency
    @staticmethod
    def _node_scope(scope,node):
        return EffectiveScope(scope.principal_id,scope.tenant_id,tuple(node.domains),scope.source_ids,scope.access_labels,scope.processing_classes,scope.policy_epoch,scope.private_state_allowed)
    async def _run_node(self,plan,node,deadline,cancel_token,prior):
        if cancel_token is not None and cancel_token.is_set():return ChannelResult(ChannelStatus.REJECTED,reason="request cancelled")
        scope=self._node_scope(plan.scope,node)
        if node.operation==PlanOperation.EXACT:
            if self.exact_index is None:return ExactLookupResult(ExactLookupStatus.REJECTED,reason="exact capability unavailable")
            return self.exact_index.lookup(ExactLookupRequest(node.query,scope,plan.temporal,plan.snapshot))
        if node.operation in (PlanOperation.LEXICAL,PlanOperation.DENSE):
            port=self.search_ports.get(node.operation.value)
            if port is None:return ChannelResult(ChannelStatus.UNSUPPORTED,reason=f"{node.operation.value} capability unavailable")
            kind=SearchKind.LEXICAL if node.operation==PlanOperation.LEXICAL else SearchKind.DENSE
            budget=CandidateBudget(node.candidate_limit,lexical=node.candidate_limit if kind==SearchKind.LEXICAL else None,dense=node.candidate_limit if kind==SearchKind.DENSE else None)
            return await port.search(SearchRequest(node.query,kind,scope,plan.temporal,budget,plan.snapshot,deadline,cancel_token))
        if node.operation==PlanOperation.GRAPH:
            if self.graph_port is None:return ChannelResult(ChannelStatus.UNSUPPORTED,reason="graph capability unavailable")
            return await self.graph_port.run(node,scope,plan.snapshot,prior,deadline,cancel_token)
        if node.operation==PlanOperation.STRUCTURED:
            if self.structured_port is None:return ChannelResult(ChannelStatus.UNSUPPORTED,reason="structured capability unavailable")
            return await self.structured_port.run(node,scope,plan.snapshot,prior,deadline,cancel_token)
        return ChannelResult(ChannelStatus.UNSUPPORTED,reason="unsupported plan operation")
    async def execute(self,plan,cancellation_token=None):
        started=datetime.now(timezone.utc); deadline=started+timedelta(milliseconds=plan.budget.deadline_ms); remaining={n.node_id:n for n in plan.nodes}; done={}; ordered=[]; sem=asyncio.Semaphore(self.max_concurrency)
        async def bounded(node):
            async with sem:
                seconds=max(0.0,(deadline-datetime.now(timezone.utc)).total_seconds())
                if seconds<=0:return ChannelResult(ChannelStatus.TIMEOUT,reason="request deadline exceeded")
                try:return await asyncio.wait_for(self._run_node(plan,node,deadline,cancellation_token,done),timeout=seconds)
                except asyncio.TimeoutError:return ChannelResult(ChannelStatus.TIMEOUT,reason="node deadline exceeded")
        while remaining:
            ready=[n for n in remaining.values() if all(dep in done for dep in n.dependencies)]
            if not ready: raise RuntimeError("validated plan became unschedulable")
            tasks=[asyncio.create_task(bounded(n)) for n in ready]
            if cancellation_token is not None:
                watcher=asyncio.create_task(cancellation_token.wait()); aggregate=asyncio.gather(*tasks)
                finished,_=await asyncio.wait((aggregate,watcher),return_when=asyncio.FIRST_COMPLETED)
                if watcher in finished and cancellation_token.is_set():
                    for task in tasks:task.cancel()
                    aggregate.cancel(); await asyncio.gather(*tasks,return_exceptions=True); await asyncio.gather(aggregate,return_exceptions=True)
                    for n in ready:
                        result=ChannelResult(ChannelStatus.REJECTED,reason="request cancelled"); done[n.node_id]=result; ordered.append(NodeExecution(n,result)); remaining.pop(n.node_id,None)
                    break
                results=aggregate.result(); watcher.cancel()
            else:results=await asyncio.gather(*tasks)
            for n,result in zip(ready,results):
                done[n.node_id]=result; ordered.append(NodeExecution(n,result)); remaining.pop(n.node_id,None)
        gaps=list(plan.gaps)
        for item in ordered:
            r=item.result
            if isinstance(r,ChannelResult) and r.status in (ChannelStatus.UNSUPPORTED,ChannelStatus.UNAVAILABLE,ChannelStatus.TIMEOUT,ChannelStatus.REJECTED): gaps.append(PlanGap(item.node.operation.value,r.reason or r.status.value,item.node.subquestion_id))
            if isinstance(r,ExactLookupResult) and item.node.required and r.status!=ExactLookupStatus.FOUND:gaps.append(PlanGap("exact",r.reason or r.status.value,item.node.subquestion_id))
        return QueryExecution(plan.plan_id,tuple(ordered),tuple(gaps),started,datetime.now(timezone.utc))
