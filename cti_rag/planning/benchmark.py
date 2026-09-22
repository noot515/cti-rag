"""Minimal public-fixture B1/B2/B3 benchmark accounting; fake dense rankings are mechanics-only."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class BenchmarkResult:
    name:str
    reciprocal_rank:float
    recall_at_k:float
    scope_hash:str
    snapshot_id:str
    semantic_quality_claim:bool=False

def _metrics(ranking,relevant,k):
    ranking=tuple(ranking); rr=0.0
    for i,uid in enumerate(ranking,1):
        if uid in relevant:rr=1.0/i;break
    denom=max(1,len(relevant)); recall=len(set(ranking[:k])&set(relevant))/denom
    return rr,recall

def run_b123_fixture(*,scope_hash,snapshot_id,relevant,exact_ranking,lexical_ranking,fused_ranking,k=10):
    out=[]
    for name,ranking in (("B1-exact",exact_ranking),("B2-lexical",lexical_ranking),("B3-grouped-fusion",fused_ranking)):
        rr,recall=_metrics(ranking,set(relevant),k); out.append(BenchmarkResult(name,rr,recall,scope_hash,snapshot_id,False))
    return tuple(out)
