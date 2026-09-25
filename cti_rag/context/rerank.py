"""Single centrally owned optional passage reranking stage."""
from __future__ import annotations
import asyncio
from datetime import datetime,timezone
from cti_rag.ports import ModelOperation,ModelRequest,PolicyDenied
from .models import EvidencePassage,RerankedPassage,RerankOutcome

class PassageReranker:
    def __init__(self,policy,model,destination,max_candidates=60):
        if max_candidates<=0:raise ValueError("max_candidates must be positive")
        self.policy=policy; self.model=model; self.destination=destination; self.max_candidates=max_candidates
    def _fallback(self,candidates,reasons=()):
        rows=tuple(RerankedPassage(c,i,i,c.fused.score,None) for i,c in enumerate(candidates,1))
        return RerankOutcome(rows,bool(reasons),tuple(reasons),None)
    async def rerank(self,query,candidates,scope,deadline=None,candidate_limit=None):
        candidates=tuple(candidates)[:min(self.max_candidates,candidate_limit or self.max_candidates)]
        if not candidates:return RerankOutcome(())
        if deadline is not None and datetime.now(timezone.utc)>=deadline:return self._fallback(candidates,("reranker_deadline",))
        # Preauthorize the whole provider-visible pool before any text is dispatched.
        try:
            for item in candidates:self.policy.authorize_model(scope,item.labels,ModelOperation.RERANK.value,self.destination)
        except Exception as exc:
            return self._fallback(candidates,(f"reranker_policy_{type(exc).__name__}",))
        inputs=tuple({"query":query,"passage_uid":item.passage.passage_uid,"text":item.passage.text} for item in candidates)
        labels=candidates[0].labels
        request=ModelRequest(ModelOperation.RERANK,inputs,scope,labels,self.destination)
        try:
            if deadline is None:result=await self.model.invoke(request)
            else:
                seconds=max(0.0,(deadline-datetime.now(timezone.utc)).total_seconds())
                if seconds<=0:return self._fallback(candidates,("reranker_deadline",))
                result=await asyncio.wait_for(self.model.invoke(request),seconds)
            scores=result.get("scores") if isinstance(result,dict) else result
            scores=tuple(float(v) for v in scores)
            if len(scores)!=len(candidates):raise ValueError("reranker score count mismatch")
        except Exception as exc:
            return self._fallback(candidates,(f"reranker_failure_{type(exc).__name__}",))
        order=sorted(range(len(candidates)),key=lambda i:(-scores[i],candidates[i].passage.passage_uid))
        fingerprint=getattr(getattr(self.model,"capabilities",None),"model_fingerprint",None)
        rows=[]
        for rank,index in enumerate(order,1):
            item=candidates[index]; rows.append(RerankedPassage(item,index+1,rank,scores[index],scores[index]))
        return RerankOutcome(tuple(rows),False,(),fingerprint)
