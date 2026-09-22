"""Milvus SearchPort wrapper for new compatible collections; legacy KnowledgeBase behavior is untouched."""
from __future__ import annotations
from datetime import datetime,timezone
import json,re
from cti_rag.contracts import PassageHit,ProvenanceRef,ScoreDirection,ScoreMetadata,TemporalMode,locator_from_dict,namespaced_uid,sha256_hex
from cti_rag.ports import BackendCapabilities,ChannelResult,ChannelStatus,SearchKind
from cti_rag.snapshots import ProjectionGeneration,ProjectionPayload

_SAFE=re.compile(r"[^A-Za-z0-9_]")
def _esc(v): return str(v).replace("\\","\\\\").replace('"','\\"')
def _iso(v): return None if v is None else v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

class MilvusDenseSearchPort:
    kind="dense"
    capabilities=BackendCapabilities(
        supported_filters=frozenset({"tenant","domain","access_label","source","temporal"}),
        temporal_modes=frozenset({TemporalMode.CURRENT,TemporalMode.HISTORICAL_PUBLIC,TemporalMode.HISTORICAL_SYSTEM_REPLAY}),
        snapshot_support=True,requires_snapshot=True,cancellation=False,max_batch_size=1000,score_direction=ScoreDirection.HIGHER_IS_BETTER,
    )
    def __init__(self,client,catalog,query_embedder,fingerprint,collection_prefix="cti_dense"):
        self.client=client; self.catalog=catalog; self.query_embedder=query_embedder; self.fingerprint=fingerprint; self.collection_prefix=_SAFE.sub("_",collection_prefix)
    def collection_name(self,generation_id):
        suffix=sha256_hex({"generation":generation_id,"fingerprint":self.fingerprint.fingerprint_id})[:20]
        return f"{self.collection_prefix}_{self.fingerprint.short_id}_{suffix}"
    def create_compatible_collection(self,generation_id):
        from pymilvus import DataType
        name=self.collection_name(generation_id)
        if self.client.has_collection(collection_name=name): return name
        schema=self.client.create_schema(auto_id=False,enable_dynamic_field=False)
        schema.add_field(field_name="passage_uid",datatype=DataType.VARCHAR,is_primary=True,max_length=160)
        schema.add_field(field_name="vector",datatype=DataType.FLOAT_VECTOR,dim=self.fingerprint.dimension)
        for field,length in (("revision_uid",160),("object_uid",160),("domain",64),("source_id",160),("tenant_id",160),("access_label",32),("available_at",40),("valid_from",40),("valid_to",40),("locator_json",8192),("original_text",65535),("embedding_fingerprint_id",64)):
            schema.add_field(field_name=field,datatype=DataType.VARCHAR,max_length=length)
        self.client.create_collection(collection_name=name,schema=schema)
        params=self.client.prepare_index_params()
        metric={"cosine":"COSINE","inner_product":"IP","l2":"L2"}[self.fingerprint.distance_metric.value]
        params.add_index(field_name="vector",index_type="AUTOINDEX",metric_type=metric)
        self.client.create_index(collection_name=name,index_params=params); self.client.load_collection(collection_name=name)
        return name
    def build(self,request,records,fingerprint):
        if fingerprint.fingerprint_id!=self.fingerprint.fingerprint_id: raise ValueError("Milvus adapter embedding fingerprint mismatch")
        if request.kind!="dense": raise ValueError("dense builder received non-dense request")
        records=tuple(sorted(records,key=lambda r:r.passage_uid)); revisions=tuple(sorted(request.revision_uids)); allowed=set(revisions)
        if any(r.revision_uid not in allowed or r.embedding_fingerprint_id!=fingerprint.fingerprint_id for r in records): raise ValueError("incompatible dense record")
        name=self.create_compatible_collection(request.generation_id)
        data=[{"passage_uid":r.passage_uid,"vector":list(r.vector),"revision_uid":r.revision_uid,"object_uid":r.object_uid,"domain":r.domain,"source_id":r.source_id,"tenant_id":r.tenant_id,"access_label":r.access_label.value,"available_at":_iso(r.available_at) or "","valid_from":_iso(r.valid_from) or "","valid_to":_iso(r.valid_to) or "","locator_json":r.locator_json,"original_text":r.original_text,"embedding_fingerprint_id":fingerprint.fingerprint_id} for r in records]
        if data:self.client.insert(collection_name=name,data=data)
        payloads=tuple(ProjectionPayload(r.passage_uid,r.revision_uid,r.locator_json,sha256_hex(r.original_text.encode("utf-8")),r.original_text) for r in records)
        checksum=sha256_hex({"collection":name,"records":[r.passage_uid for r in records],"fingerprint":fingerprint.fingerprint_id})
        return ProjectionGeneration(request.generation_id,"dense",revisions,(fingerprint.fingerprint_id,),checksum,True,True,True,request.quarantined_count,tuple(request.supported_query_capabilities),datetime.now(timezone.utc),payloads)
    def validate(self,generation):
        return bool(self.client.has_collection(collection_name=self.collection_name(generation.generation_id)))
    def cleanup(self,generation_id):
        name=self.collection_name(generation_id)
        if self.client.has_collection(collection_name=name): self.client.drop_collection(collection_name=name)
    def _filter(self,request):
        tenants=tuple(dict.fromkeys((request.scope.tenant_id,"public")))
        parts=["tenant_id in ["+",".join(f'\"{_esc(v)}\"' for v in tenants)+"]","domain in ["+",".join(f'\"{_esc(v)}\"' for v in request.scope.domains)+"]","access_label in ["+",".join(f'\"{_esc(v.value)}\"' for v in request.scope.access_labels)+"]"]
        if request.scope.source_ids: parts.append("source_id in ["+",".join(f'\"{_esc(v)}\"' for v in request.scope.source_ids)+"]")
        if request.temporal.mode==TemporalMode.HISTORICAL_PUBLIC: parts.append(f'available_at != "" and available_at <= "{_esc(request.temporal.cutoff_iso)}"')
        elif request.temporal.mode==TemporalMode.CURRENT: parts.append(f'(available_at == "" or available_at <= "{_iso(datetime.now(timezone.utc))}")')
        revoked=tuple(self.catalog.revoked_uids())
        if revoked:
            vals=",".join(f'\"{_esc(v)}\"' for v in revoked); parts.append(f"passage_uid not in [{vals}]"); parts.append(f"revision_uid not in [{vals}]"); parts.append(f"object_uid not in [{vals}]")
        parts.append(f'embedding_fingerprint_id == "{self.fingerprint.fingerprint_id}"')
        return " and ".join(parts)
    async def search(self,request):
        if request.kind!=SearchKind.DENSE:return ChannelResult(ChannelStatus.REJECTED,reason="Milvus dense adapter only supports dense search")
        if request.snapshot is None:return ChannelResult(ChannelStatus.REJECTED,reason="dense backend requires pinned snapshot")
        generation_id=self.catalog.generation_for_manifest(request.snapshot.manifest_id,"dense")
        if generation_id is None:return ChannelResult(ChannelStatus.REJECTED,reason="snapshot has no dense generation")
        if self.query_embedder.fingerprint.fingerprint_id!=self.fingerprint.fingerprint_id:return ChannelResult(ChannelStatus.REJECTED,reason="query embedding fingerprint incompatible with dense collection")
        if request.deadline is not None and datetime.now(timezone.utc)>=request.deadline:return ChannelResult(ChannelStatus.TIMEOUT,reason="dense deadline exceeded before embedding")
        vector=await self.query_embedder.embed_query(request.query,request.scope)
        if request.deadline is not None and datetime.now(timezone.utc)>=request.deadline:return ChannelResult(ChannelStatus.TIMEOUT,reason="dense deadline exceeded before Milvus search")
        name=self.collection_name(generation_id); limit=min(request.budget.total,request.budget.dense or request.budget.total)
        try:
            rows=self.client.search(collection_name=name,data=[list(vector)],filter=self._filter(request),limit=limit,output_fields=["passage_uid","revision_uid","object_uid","locator_json","original_text","embedding_fingerprint_id"])[0]
        except Exception as exc:return ChannelResult(ChannelStatus.UNAVAILABLE,reason=f"Milvus search failed: {type(exc).__name__}")
        if not rows:return ChannelResult(ChannelStatus.EMPTY,reason="no authorized dense matches")
        hits=[]
        for rank,row in enumerate(rows,1):
            entity=row.get("entity",row); passage_uid=str(entity["passage_uid"]); revision_uid=str(entity["revision_uid"]); locator=locator_from_dict(json.loads(entity["locator_json"])); score=float(row.get("distance",row.get("score",0.0)))
            hit_id=namespaced_uid("hit","dense.search",{"manifest":request.snapshot.manifest_id,"passage_uid":passage_uid,"query":request.query,"fingerprint":self.fingerprint.fingerprint_id})
            hits.append(PassageHit(hit_id,passage_uid,revision_uid,ProvenanceRef(revision_uid,locator),str(entity["original_text"]),(ScoreMetadata("dense",score,ScoreDirection.HIGHER_IS_BETTER,rank,f"milvus:{self.fingerprint.short_id}"),)))
        return ChannelResult(ChannelStatus.OK,tuple(hits))
