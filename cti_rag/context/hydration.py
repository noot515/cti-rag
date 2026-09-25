"""Canonical evidence hydration before reranking/model exposure."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from cti_rag.contracts import PolicyLabels,PassageHit
from .models import EvidencePassage

@dataclass(frozen=True)
class PassageMetadata:
    labels:PolicyLabels
    source_id:str
    origin_group:str
    snapshot_manifest_id:str
    available_at:Optional[datetime]=None
    epistemic_label:str="source_claim"
    unit:Optional[str]=None
    parent_uid:Optional[str]=None
    conflict_group:Optional[str]=None
    entity_key:Optional[str]=None
    valid_time:Optional[str]=None
    edition_key:Optional[str]=None

@dataclass(frozen=True)
class HydrationProfile:
    candidate_count:int
    evidence_backend_calls:int
    metadata_backend_calls:int
    bulk_evidence_used:bool
    bulk_metadata_used:bool

class EvidenceHydrator:
    def __init__(self,evidence_store,metadata_provider,enable_bulk=False,max_batch_size=64):
        if max_batch_size<=0:raise ValueError("max_batch_size must be positive")
        self.evidence_store=evidence_store;self.metadata_provider=metadata_provider
        self.enable_bulk=bool(enable_bulk);self.max_batch_size=int(max_batch_size)

    @staticmethod
    def _normalize_many(value,uids):
        if value is None:return {}
        if isinstance(value,dict):return {str(k):v for k,v in value.items()}
        rows=tuple(value)
        if len(rows)!=len(uids):raise ValueError("bulk hydration result must align with requested passage_uids")
        return dict(zip(uids,rows))

    def _load(self,provider,uids,point_name,bulk_name):
        if provider is None:return {},0,False
        bulk=getattr(provider,bulk_name,None)
        if self.enable_bulk and callable(bulk):
            out={};calls=0
            for start in range(0,len(uids),self.max_batch_size):
                batch=tuple(uids[start:start+self.max_batch_size]);out.update(self._normalize_many(bulk(batch),batch));calls+=1
            return out,calls,True
        point=getattr(provider,point_name)
        return {uid:point(uid) for uid in uids},len(uids),False

    def hydrate_profiled(self,fused_passages,scope,snapshot):
        fused_passages=tuple(fused_passages);uids=tuple(f.passage.passage_uid for f in fused_passages)
        canonical_by_uid,evidence_calls,bulk_evidence=self._load(self.evidence_store,uids,"get_passage","get_passages")
        metadata_by_uid,metadata_calls,bulk_metadata=self._load(self.metadata_provider,uids,"get","get_many")
        out=[];denied=0;invalid=0
        for fused in fused_passages:
            hit=fused.passage;canonical=canonical_by_uid.get(hit.passage_uid);metadata=metadata_by_uid.get(hit.passage_uid)
            if canonical is None or metadata is None:invalid+=1;continue
            provenance=getattr(canonical,"provenance",None);text=getattr(canonical,"text",None);revision_uid=getattr(canonical,"revision_uid",None)
            if revision_uid!=hit.revision_uid or provenance!=hit.provenance or text!=hit.text:invalid+=1;continue
            if metadata.snapshot_manifest_id!=snapshot.manifest_id:invalid+=1;continue
            if metadata.labels.tenant_id not in (scope.tenant_id,"public") or metadata.labels.access_label not in scope.access_labels or metadata.labels.processing_class not in scope.processing_classes:
                denied+=1;continue
            canonical_hit=PassageHit(hit.hit_id,hit.passage_uid,hit.revision_uid,provenance,text,hit.scores)
            canonical_fused=type(fused)(canonical_hit,fused.score,fused.channel_ranks,fused.subquestion_id)
            out.append(EvidencePassage(canonical_fused,metadata.labels,metadata.source_id,metadata.origin_group,metadata.snapshot_manifest_id,metadata.available_at,metadata.epistemic_label,metadata.unit,metadata.parent_uid,metadata.conflict_group,metadata.entity_key,metadata.valid_time,metadata.edition_key))
        profile=HydrationProfile(len(fused_passages),evidence_calls,metadata_calls,bulk_evidence,bulk_metadata)
        return tuple(out),denied,invalid,profile

    def hydrate(self,fused_passages,scope,snapshot):
        out,denied,invalid,_profile=self.hydrate_profiled(fused_passages,scope,snapshot)
        return out,denied,invalid
