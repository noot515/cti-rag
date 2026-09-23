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

class EvidenceHydrator:
    def __init__(self,evidence_store,metadata_provider):
        self.evidence_store=evidence_store;self.metadata_provider=metadata_provider
    def hydrate(self,fused_passages,scope,snapshot):
        out=[];denied=0;invalid=0
        for fused in fused_passages:
            hit=fused.passage
            canonical=self.evidence_store.get_passage(hit.passage_uid) if self.evidence_store is not None else None
            metadata=self.metadata_provider.get(hit.passage_uid) if self.metadata_provider is not None else None
            if canonical is None or metadata is None:invalid+=1;continue
            provenance=getattr(canonical,"provenance",None);text=getattr(canonical,"text",None);revision_uid=getattr(canonical,"revision_uid",None)
            if revision_uid!=hit.revision_uid or provenance!=hit.provenance or text!=hit.text:invalid+=1;continue
            if metadata.snapshot_manifest_id!=snapshot.manifest_id:invalid+=1;continue
            if metadata.labels.tenant_id not in (scope.tenant_id,"public") or metadata.labels.access_label not in scope.access_labels or metadata.labels.processing_class not in scope.processing_classes:
                denied+=1;continue
            canonical_hit=PassageHit(hit.hit_id,hit.passage_uid,hit.revision_uid,provenance,text,hit.scores)
            canonical_fused=type(fused)(canonical_hit,fused.score,fused.channel_ranks,fused.subquestion_id)
            out.append(EvidencePassage(canonical_fused,metadata.labels,metadata.source_id,metadata.origin_group,metadata.snapshot_manifest_id,metadata.available_at,metadata.epistemic_label,metadata.unit,metadata.parent_uid))
        return tuple(out),denied,invalid
