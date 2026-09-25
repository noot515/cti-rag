"""B4 reranking/context mechanics accounting with explicit non-semantic fake status."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class B4Comparison:
    b3_reciprocal_rank:float
    b4_reciprocal_rank:float
    b3_recall_at_k:float
    b4_recall_at_k:float
    scope_hash:str
    snapshot_id:str
    real_model_status:str
    semantic_quality_claim:bool=False

def _metrics(ranking,relevant,k):
    rr=0.0
    for i,uid in enumerate(tuple(ranking),1):
        if uid in relevant:rr=1/i;break
    recall=len(set(tuple(ranking)[:k])&set(relevant))/max(1,len(relevant))
    return rr,recall

def compare_b4_to_b3(*,b3_ranking,b4_ranking,relevant,k,scope_hash,snapshot_id,real_model_status="not_run"):
    b3rr,b3r=_metrics(b3_ranking,set(relevant),k);b4rr,b4r=_metrics(b4_ranking,set(relevant),k)
    return B4Comparison(b3rr,b4rr,b3r,b4r,scope_hash,snapshot_id,real_model_status,False)
