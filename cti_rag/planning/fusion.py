"""Grouped reciprocal-rank fusion over passage channels with evidence obligations kept outside competition."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple
from cti_rag.contracts import PassageHit,sha256_hex
from cti_rag.ports import ChannelResult,ChannelStatus
from cti_rag.retrieval import merge_passage_hits
from .models import PlanOperation

@dataclass(frozen=True)
class FusedPassage:
    passage:PassageHit
    score:float
    channel_ranks:Tuple[Tuple[str,int],...]
    subquestion_id:str
@dataclass(frozen=True)
class FusionResult:
    passages:Tuple[FusedPassage,...]
    exact_obligations:Tuple[object,...]
    structured_obligations:Tuple[object,...]
    gaps:Tuple[object,...]
    channel_statuses:Tuple[Tuple[str,str],...]
    configuration_hash:str
    graph_paths:Tuple[object,...]=()
    join_results:Tuple[object,...]=()

def _variant_group(executions,k):
    unique={}
    for item in sorted(executions,key=lambda x:x.node.node_id):unique.setdefault(item.node.variant_key,item)
    contributions={}; representatives={}
    for item in unique.values():
        result=item.result
        if not isinstance(result,ChannelResult) or result.status!=ChannelStatus.OK:continue
        for rank,hit in enumerate(result.items,1):
            contributions[hit.passage_uid]=contributions.get(hit.passage_uid,0.0)+1.0/(k+rank)
            representatives.setdefault(hit.passage_uid,[]).append(hit)
    denom=max(1,len(unique)); scored=[]
    for uid,total in contributions.items():
        passage=merge_passage_hits((tuple(representatives[uid]),))[0]; scored.append((uid,total/denom,passage))
    return tuple(sorted(scored,key=lambda x:(-x[1],x[0])))

def grouped_rrf(execution,k=60,top_k=20):
    if k<=0 or top_k<=0:raise ValueError("RRF k/top_k must be positive")
    passage_exec=[]; exact=[]; structured=[]; graph_paths=[]; joins=[]; statuses=[]
    for item in execution.nodes:
        op=item.node.operation; result=item.result
        if op in (PlanOperation.LEXICAL,PlanOperation.DENSE):
            passage_exec.append(item); statuses.append((item.node.node_id,getattr(getattr(result,"status",None),"value",str(getattr(result,"status","unknown")))))
        elif op==PlanOperation.EXACT:exact.append(result)
        elif op==PlanOperation.STRUCTURED:structured.append(result)
        elif op==PlanOperation.GRAPH:
            statuses.append((item.node.node_id,getattr(getattr(result,"status",None),"value",str(getattr(result,"status","unknown")))))
            if isinstance(result,ChannelResult) and result.status==ChannelStatus.OK:graph_paths.extend(result.items)
        elif op==PlanOperation.JOIN:
            joins.append(result);statuses.append((item.node.node_id,getattr(getattr(result,"status",None),"value",str(getattr(result,"status","unknown")))))
    channel_groups={}
    for item in passage_exec:channel_groups.setdefault((item.node.subquestion_id,item.node.operation.value),[]).append(item)
    channel_rankings={key:_variant_group(items,k) for key,items in channel_groups.items()}
    subquestions=sorted({key[0] for key in channel_rankings}); per_subq={}
    for subq in subquestions:
        channels=sorted((key,ranking) for key,ranking in channel_rankings.items() if key[0]==subq)
        totals={}; ranks={}; reps={}
        for (_sq,channel),ranking in channels:
            for rank,(uid,_inner,passage) in enumerate(ranking,1):
                totals[uid]=totals.get(uid,0.0)+1.0/(k+rank); ranks.setdefault(uid,[]).append((channel,rank)); reps.setdefault(uid,[]).append(passage)
        fused=[]
        for uid,score in totals.items():
            passage=merge_passage_hits((tuple(reps[uid]),))[0]; fused.append(FusedPassage(passage,score,tuple(sorted(ranks[uid])),subq))
        per_subq[subq]=sorted(fused,key=lambda x:(-x.score,x.passage.passage_uid))
    output=[]; index=0
    while len(output)<top_k:
        added=False
        for subq in subquestions:
            rows=per_subq.get(subq,())
            if index<len(rows):output.append(rows[index]);added=True
            if len(output)>=top_k:break
        if not added:break
        index+=1
    config_hash=sha256_hex({"method":"grouped_rrf","k":k,"top_k":top_k,"channels":tuple(sorted(channel_groups))})
    return FusionResult(tuple(output),tuple(exact),tuple(structured),execution.gaps,tuple(statuses),config_hash,tuple(graph_paths),tuple(joins))
