"""Deterministic exhaustive dense backend used for contract tests and ANN-oracle evaluation."""
from __future__ import annotations
from datetime import datetime,timezone
import json,math
from cti_rag.contracts import PassageHit,ProvenanceRef,ScoreDirection,ScoreMetadata,TemporalMode,locator_from_dict,namespaced_uid,sha256_hex
from cti_rag.ports import BackendCapabilities,ChannelResult,ChannelStatus,SearchKind
from cti_rag.snapshots import ProjectionGeneration,ProjectionPayload
from .models import DistanceMetric

def _cos(a,b):
    dot=sum(x*y for x,y in zip(a,b)); na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b)); return 0.0 if na==0 or nb==0 else dot/(na*nb)
def _ip(a,b): return sum(x*y for x,y in zip(a,b))
def _neg_l2(a,b): return -math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))

class InMemoryDenseIndex:
    kind="dense"
    capabilities=BackendCapabilities(
        supported_filters=frozenset({"tenant","domain","access_label","source","temporal"}),
        temporal_modes=frozenset({TemporalMode.CURRENT,TemporalMode.HISTORICAL_PUBLIC,TemporalMode.HISTORICAL_SYSTEM_REPLAY}),
        snapshot_support=True,requires_snapshot=True,cancellation=True,max_batch_size=1000,score_direction=ScoreDirection.HIGHER_IS_BETTER,
    )
    def __init__(self,catalog,query_embedder):
        self.catalog=catalog; self.query_embedder=query_embedder; self._generations={}; self._fingerprints={}
    def build(self,request,records,fingerprint):
        if request.kind!="dense": raise ValueError("dense builder received non-dense request")
        records=tuple(sorted(records,key=lambda r:r.passage_uid)); revisions=tuple(sorted(request.revision_uids)); allowed=set(revisions)
        if any(r.revision_uid not in allowed for r in records): raise ValueError("dense record revision outside projection revision set")
        if any(r.embedding_fingerprint_id!=fingerprint.fingerprint_id for r in records): raise ValueError("mixed embedding spaces are forbidden")
        if request.representation_versions and tuple(request.representation_versions)!=(fingerprint.fingerprint_id,): raise ValueError("projection representation version does not match embedding fingerprint")
        if any(len(r.vector)!=fingerprint.dimension for r in records): raise ValueError("dense vector dimension mismatch")
        checksum=sha256_hex({"generation_id":request.generation_id,"fingerprint":fingerprint.fingerprint_id,"records":[{"passage":r.passage_uid,"revision":r.revision_uid,"vector":r.vector} for r in records]})
        existing=self._generations.get(request.generation_id)
        if existing:
            if existing[0]!=checksum: raise ValueError("immutable dense generation collision")
            return existing[2]
        payloads=tuple(ProjectionPayload(r.passage_uid,r.revision_uid,r.locator_json,sha256_hex(r.original_text.encode("utf-8")),r.original_text) for r in records)
        generation=ProjectionGeneration(request.generation_id,"dense",revisions,(fingerprint.fingerprint_id,),checksum,True,True,True,request.quarantined_count,tuple(request.supported_query_capabilities),datetime.now(timezone.utc),payloads)
        self._generations[request.generation_id]=(checksum,records,generation); self._fingerprints[request.generation_id]=fingerprint
        return generation
    def validate(self,generation):
        current=self._generations.get(generation.generation_id); return bool(current and current[0]==generation.checksum)
    def cleanup(self,generation_id): self._generations.pop(generation_id,None); self._fingerprints.pop(generation_id,None)
    def eligible_records(self,request,generation_id):
        row=self._generations.get(generation_id)
        if row is None:return ()
        records=row[1]; now=datetime.now(timezone.utc); out=[]; revoked=set(self.catalog.revoked_uids())
        for r in records:
            if r.passage_uid in revoked or r.revision_uid in revoked or r.object_uid in revoked: continue
            if r.tenant_id not in (request.scope.tenant_id,"public") or r.domain not in request.scope.domains or r.access_label not in request.scope.access_labels: continue
            if request.scope.source_ids and r.source_id not in request.scope.source_ids: continue
            if request.temporal.mode==TemporalMode.HISTORICAL_PUBLIC:
                cutoff=datetime.fromisoformat(request.temporal.cutoff_iso.replace("Z","+00:00"))
                if r.available_at is None or r.available_at>cutoff: continue
            elif request.temporal.mode==TemporalMode.CURRENT and r.available_at is not None and r.available_at>now: continue
            out.append(r)
        return tuple(out)
    def exhaustive_rank(self,query_vector,records,fingerprint):
        if fingerprint.distance_metric==DistanceMetric.COSINE: score=_cos
        elif fingerprint.distance_metric==DistanceMetric.INNER_PRODUCT: score=_ip
        else: score=_neg_l2
        return tuple(sorted(((r,score(query_vector,r.vector)) for r in records),key=lambda x:(-x[1],x[0].passage_uid)))
    async def search(self,request):
        if request.kind!=SearchKind.DENSE:return ChannelResult(ChannelStatus.REJECTED,reason="dense backend only supports dense search")
        if request.snapshot is None:return ChannelResult(ChannelStatus.REJECTED,reason="dense backend requires pinned snapshot")
        generation_id=self.catalog.generation_for_manifest(request.snapshot.manifest_id,"dense")
        if generation_id is None:return ChannelResult(ChannelStatus.REJECTED,reason="snapshot has no dense generation")
        fingerprint=self._fingerprints.get(generation_id)
        if fingerprint is None:return ChannelResult(ChannelStatus.UNAVAILABLE,reason="dense generation unavailable")
        if fingerprint.fingerprint_id!=self.query_embedder.fingerprint.fingerprint_id:return ChannelResult(ChannelStatus.REJECTED,reason="query embedding fingerprint incompatible with dense generation")
        if request.cancellation_token is not None and getattr(request.cancellation_token,"is_set",lambda:False)(): return ChannelResult(ChannelStatus.REJECTED,reason="request cancelled")
        if request.deadline is not None and datetime.now(timezone.utc)>=request.deadline:return ChannelResult(ChannelStatus.TIMEOUT,reason="dense deadline exceeded before embedding")
        vector=await self.query_embedder.embed_query(request.query,request.scope)
        if request.deadline is not None and datetime.now(timezone.utc)>=request.deadline:return ChannelResult(ChannelStatus.TIMEOUT,reason="dense deadline exceeded before search")
        eligible=self.eligible_records(request,generation_id); limit=min(request.budget.total,request.budget.dense or request.budget.total)
        ranked=self.exhaustive_rank(vector,eligible,fingerprint)[:limit]
        if not ranked:return ChannelResult(ChannelStatus.EMPTY,reason="no authorized dense matches")
        hits=[]
        for rank,(record,score) in enumerate(ranked,1):
            loc=locator_from_dict(json.loads(record.locator_json)); hit_id=namespaced_uid("hit","dense.search",{"manifest":request.snapshot.manifest_id,"passage_uid":record.passage_uid,"query":request.query,"fingerprint":fingerprint.fingerprint_id})
            hits.append(PassageHit(hit_id,record.passage_uid,record.revision_uid,ProvenanceRef(record.revision_uid,loc),record.original_text,(ScoreMetadata("dense",float(score),ScoreDirection.HIGHER_IS_BETTER,rank,f"exhaustive:{fingerprint.short_id}"),)))
        return ChannelResult(ChannelStatus.OK,tuple(hits))
