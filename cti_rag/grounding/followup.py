"""Single-hop follow-up retrieval that cannot widen scope or recurse."""
from __future__ import annotations
from cti_rag.contracts import CandidateBudget
from cti_rag.ports import ChannelResult,ChannelStatus,SearchKind,SearchRequest
from .models import FollowUpOutcome,FollowUpProposal

class BoundedFollowUpSearch:
    def __init__(self,search_port,*,remaining_calls=1,remaining_tokens=1200,token_counter=None):
        if remaining_calls<0 or remaining_tokens<0:raise ValueError("follow-up budgets cannot be negative")
        self.search_port=search_port;self.remaining_calls=min(1,remaining_calls);self.remaining_tokens=remaining_tokens;self.token_counter=token_counter or (lambda text:max(1,len(str(text).split())));self._used=False
    async def search(self,proposal:FollowUpProposal,*,original_plan,kind:SearchKind=SearchKind.LEXICAL):
        if self._used:return FollowUpOutcome(False,False,"follow-up already consumed")
        if proposal.depth!=0:return FollowUpOutcome(False,False,"recursive follow-up proposals are forbidden")
        planned_calls=len(getattr(original_plan,"nodes",()));max_calls=getattr(getattr(original_plan,"budget",None),"max_backend_calls",None)
        if max_calls is not None and planned_calls>=max_calls:return FollowUpOutcome(False,False,"global backend-call budget exhausted by original plan")
        if self.remaining_calls<1:return FollowUpOutcome(False,False,"global backend-call budget exhausted")
        if proposal.max_tokens>self.remaining_tokens:return FollowUpOutcome(False,False,"global follow-up token budget exceeded")
        if kind not in (SearchKind.LEXICAL,SearchKind.DENSE):return FollowUpOutcome(False,False,"follow-up is restricted to bounded passage search")
        self._used=True;self.remaining_calls-=1;self.remaining_tokens-=proposal.max_tokens
        budget=CandidateBudget(proposal.max_candidates,lexical=proposal.max_candidates if kind==SearchKind.LEXICAL else None,dense=proposal.max_candidates if kind==SearchKind.DENSE else None)
        required={"tenant","domain","access_label"}
        if original_plan.scope.source_ids:required.add("source")
        if original_plan.temporal.mode.value!="current":required.add("temporal")
        request=SearchRequest(proposal.query,kind,original_plan.scope,original_plan.temporal,budget,original_plan.snapshot,required_filters=frozenset(required))
        result=await self.search_port.search(request)
        if isinstance(result,ChannelResult) and result.status==ChannelStatus.OK:
            kept=[];used=0
            for item in result.items:
                cost=self.token_counter(getattr(item,"text",""))
                if used+cost>proposal.max_tokens:break
                kept.append(item);used+=cost
            if not kept:result=ChannelResult(ChannelStatus.EMPTY,reason="follow-up result exceeded token budget")
            elif len(kept)!=len(result.items):result=ChannelResult(ChannelStatus.OK,tuple(kept),reason=result.reason,truncated=True)
        return FollowUpOutcome(True,True,proposal.reason,result,1,proposal.max_tokens)
