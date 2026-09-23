from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime,timezone
from cti_rag.contracts import PassageHit,ProvenanceRef,ScoreDirection,ScoreMetadata,TemporalMode,locator_from_dict,namespaced_uid
from cti_rag.ports import ChannelResult,ChannelStatus

@dataclass(frozen=True)
class PhraseSearchRequest:
    phrase:str
    scope:object
    temporal:object
    snapshot:object
    limit:int=20
    def __post_init__(self):
        if not self.phrase.strip() or self.limit<=0:raise ValueError("phrase request requires text and positive limit")

class HumanitiesPhraseIndex:
    def __init__(self,documents,snapshot_manifest_id):
        self.documents=tuple(documents);self.snapshot_manifest_id=snapshot_manifest_id
    async def search(self,request:PhraseSearchRequest):
        if request.snapshot is None or request.snapshot.manifest_id!=self.snapshot_manifest_id:return ChannelResult(ChannelStatus.REJECTED,reason="phrase search requires compatible pinned snapshot")
        needle=" ".join(request.phrase.casefold().split());hits=[]
        cutoff=None
        if request.temporal.mode==TemporalMode.HISTORICAL_PUBLIC:
            if not request.temporal.cutoff_iso:return ChannelResult(ChannelStatus.REJECTED,reason="historical phrase search requires cutoff")
            cutoff=datetime.fromisoformat(request.temporal.cutoff_iso.replace("Z","+00:00")).astimezone(timezone.utc)
        for d in self.documents:
            if d.domain!="humanities" or d.tenant_id not in (request.scope.tenant_id,"public") or d.access_label not in request.scope.access_labels:continue
            if d.domain not in request.scope.domains:continue
            if request.scope.source_ids and d.source_id not in request.scope.source_ids:continue
            if cutoff is not None and (d.available_at is None or d.available_at>cutoff):continue
            if needle not in " ".join(d.normalized_text.casefold().split()):continue
            locator=locator_from_dict(json.loads(d.locator_json));rank=len(hits)+1
            hit_id=namespaced_uid("hit","humanities.phrase",{"manifest":self.snapshot_manifest_id,"passage":d.passage_uid,"phrase":needle})
            hits.append(PassageHit(hit_id,d.passage_uid,d.revision_uid,ProvenanceRef(d.revision_uid,locator),d.original_text,(ScoreMetadata("phrase",1.0,ScoreDirection.UNORDERED,rank,"humanities-substring/1"),)))
            if len(hits)>=request.limit:break
        if not hits:return ChannelResult(ChannelStatus.EMPTY,reason="phrase absent from sampled corpus; this is not evidence of historical nonexistence")
        return ChannelResult(ChannelStatus.OK,tuple(hits))
