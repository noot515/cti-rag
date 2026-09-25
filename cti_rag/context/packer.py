"""Deterministic evidence selection and tokenizer-budgeted context packing."""
from __future__ import annotations
import json,re
from dataclasses import dataclass
from typing import Optional
from cti_rag.contracts import AccessLabel
from cti_rag.planning import PlanGap
from .citations import CitationVerifier
from .models import ContextPack,EvidencePassage,PackedPassage,RerankOutcome
from .tokenizer import ContextBudget,truncate_to_tokens

def _tokens(text):
    return frozenset(re.findall(r"[A-Za-z0-9_./:-]+",text.lower()))

def _redundancy(a,b):
    aa=_tokens(a);bb=_tokens(b)
    if not aa or not bb:return 0.0
    return len(aa&bb)/len(aa|bb)

def _scope_allows(scope,item:EvidencePassage,snapshot_id):
    if item.snapshot_manifest_id!=snapshot_id:return False
    if item.labels.tenant_id not in (scope.tenant_id,"public"):return False
    if item.labels.access_label not in scope.access_labels:return False
    if item.labels.processing_class not in scope.processing_classes:return False
    return True

def _typed_summary(value):
    status=getattr(getattr(value,"status",None),"value",None)
    if status is not None:return {"type":value.__class__.__name__,"status":status}
    if hasattr(value,"result_uid"):return {"type":"structured","result_uid":value.result_uid}
    return {"type":value.__class__.__name__}

class ContextPacker:
    def __init__(self,tokenizer,evidence_store=None,parent_expander=None,min_partial_tokens=8):
        self.tokenizer=tokenizer; self.verifier=CitationVerifier(evidence_store); self.parent_expander=parent_expander; self.min_partial_tokens=min_partial_tokens
    @property
    def tokenizer_fingerprint(self):
        value=getattr(self.tokenizer,"fingerprint",None)
        if callable(value):value=value()
        return value or f"{self.tokenizer.name}:{self.tokenizer.revision}"
    async def pack(self,reranked:RerankOutcome,fusion,plan,budget:ContextBudget):
        available=min(plan.budget.max_context_tokens,budget.available); used=0; missing=list(fusion.gaps); exact=tuple(fusion.exact_obligations); structured=tuple(fusion.structured_obligations); graph_paths=tuple(getattr(fusion,"graph_paths",())); joins=tuple(getattr(fusion,"join_results",()))
        # Required typed evidence is accounted before free-text passages but always returned separately.
        for obligation in exact+structured+graph_paths+joins:
            cost=len(self.tokenizer.encode(json.dumps(_typed_summary(obligation),sort_keys=True,separators=(",",":"))))
            if used+cost<=available:used+=cost
            else:missing.append(PlanGap("required_evidence","required typed evidence does not fit context budget"))
        ranked=list(reranked.passages); selected=[]; selected_uids=set(); origins=set(); subqs=sorted({r.evidence.subquestion_id for r in ranked})
        # Coverage pass: first feasible passage per subquestion.
        for subq in subqs:
            row=next((r for r in ranked if r.evidence.subquestion_id==subq and r.evidence.passage.passage_uid not in selected_uids),None)
            if row is not None:
                packed,used=self._fit(row.evidence,used,available,plan)
                if packed is not None:selected.append(packed);selected_uids.add(row.evidence.passage.passage_uid);origins.add(row.evidence.origin_group)
        # Conflict-preservation pass: when upstream/domain logic declares a
        # conflict group, reserve evidence from distinct source origins before
        # redundancy pruning. Syndicated copies from one origin do not simulate
        # independent corroboration.
        conflict_groups={}
        for row in ranked:
            group=getattr(row.evidence,"conflict_group",None)
            if group:conflict_groups.setdefault(group,[]).append(row)
        for group in sorted(conflict_groups):
            rows=sorted(conflict_groups[group],key=lambda r:(-r.score,r.evidence.passage.passage_uid))
            group_origins={p.evidence.origin_group for p in selected if getattr(p.evidence,"conflict_group",None)==group}
            for row in rows:
                ev=row.evidence
                if ev.passage.passage_uid in selected_uids or ev.origin_group in group_origins:continue
                packed,used=self._fit(ev,used,available,plan)
                if packed is None:continue
                selected.append(packed);selected_uids.add(ev.passage.passage_uid);origins.add(ev.origin_group);group_origins.add(ev.origin_group)
                if len(group_origins)>=2:break
        # Relevance/nonredundancy pass.
        candidates=[]
        for row in ranked:
            ev=row.evidence
            if ev.passage.passage_uid in selected_uids:continue
            redundancy=max((_redundancy(ev.passage.text,p.display_text) for p in selected),default=0.0)
            origin_penalty=0.20 if ev.origin_group in origins else 0.0
            utility=row.score+0.10*(ev.subquestion_id not in {p.evidence.subquestion_id for p in selected})-0.35*redundancy-origin_penalty
            candidates.append((utility,ev))
        for _utility,ev in sorted(candidates,key=lambda x:(-x[0],x[1].passage.passage_uid)):
            packed,used=self._fit(ev,used,available,plan)
            if packed is not None:selected.append(packed);selected_uids.add(ev.passage.passage_uid);origins.add(ev.origin_group)
            if used>=available:break
        # Parent expansion happens only after reranking, and every parent is scope/snapshot checked.
        if self.parent_expander is not None:
            additions=[]
            for child in tuple(selected):
                parent=await self.parent_expander.expand(child.evidence,plan.scope,plan.snapshot)
                if parent is None or not _scope_allows(plan.scope,parent,plan.snapshot.manifest_id):continue
                if parent.passage.passage_uid in selected_uids:continue
                packed,used=self._fit(parent,used,available,plan,parent_of=child.evidence.passage.passage_uid)
                if packed is not None:additions.append(packed);selected_uids.add(parent.passage.passage_uid);origins.add(parent.origin_group)
            selected.extend(additions)
        verified=[]
        for item in selected:
            valid=self.verifier.verify(item)
            verified.append(PackedPassage(item.evidence,item.display_text,item.token_count,item.truncated,valid,item.parent_of))
            if not valid:missing.append(PlanGap("citation","packed citation failed canonical verification",item.evidence.subquestion_id))
        return ContextPack(tuple(verified),exact,structured,used,available,tuple(missing),tuple(sorted(origins)),self.tokenizer_fingerprint,graph_paths,joins)
    def _fit(self,evidence,used,available,plan,parent_of=None):
        if not _scope_allows(plan.scope,evidence,plan.snapshot.manifest_id):return None,used
        remaining=available-used
        if remaining<=0:return None,used
        text,count,truncated=truncate_to_tokens(self.tokenizer,evidence.passage.text,remaining)
        if truncated and count<self.min_partial_tokens:return None,used
        if count<=0:return None,used
        return PackedPassage(evidence,text,count,truncated,False,parent_of),used+count
