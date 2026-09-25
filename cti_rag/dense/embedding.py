"""Authorized batched embedding runtime with bounded concurrency, retries, and scoped caching."""
from __future__ import annotations
import asyncio
from collections import defaultdict
from cti_rag.ports.models import ModelOperation,ModelRequest
from cti_rag.ports.policy import ProcessingDestination
from .models import EmbeddingFingerprint,EmbeddingInput

class EmbeddingRuntime:
    def __init__(self,policy,model,cache,max_batch_size=32,max_concurrency=2,max_retries=1,max_queued_items=4096):
        if min(max_batch_size,max_concurrency,max_queued_items) <= 0 or max_retries < 0: raise ValueError("invalid embedding runtime bounds")
        self.policy=policy; self.model=model; self.cache=cache; self.max_batch_size=max_batch_size; self.max_concurrency=max_concurrency; self.max_retries=max_retries; self.max_queued_items=max_queued_items
    async def embed(self,items,scope,fingerprint:EmbeddingFingerprint,destination:ProcessingDestination):
        items=tuple(items)
        if len(items)>self.max_queued_items: raise RuntimeError("embedding queue bound exceeded")
        out=[None]*len(items); missing=[]
        for i,item in enumerate(items):
            cached=self.cache.get(item,fingerprint)
            if cached is not None:
                self._validate_vector(cached,fingerprint); out[i]=cached
            else: missing.append((i,item))
        if not missing:return tuple(out)
        groups=defaultdict(list)
        for i,item in missing:
            key=(item.labels.tenant_id,item.labels.access_label.value,item.labels.processing_class.value,item.labels.license_id,item.labels.retention_class,item.labels.markings)
            groups[key].append((i,item))
        sem=asyncio.Semaphore(self.max_concurrency)
        async def run_batch(batch):
            labels=batch[0][1].labels
            for _,item in batch:
                self.policy.authorize_model(scope,item.labels,ModelOperation.EMBEDDING.value,destination)
            texts=tuple(item.model_text for _,item in batch)
            async with sem:
                last=None
                for attempt in range(self.max_retries+1):
                    try:
                        result=await self.model.invoke(ModelRequest(ModelOperation.EMBEDDING,texts,scope,labels,destination))
                        vectors=result.get("vectors") if isinstance(result,dict) else result
                        vectors=tuple(tuple(float(v) for v in vec) for vec in vectors)
                        if len(vectors)!=len(batch): raise ValueError("embedding provider returned wrong batch length")
                        for (idx,item),vector in zip(batch,vectors):
                            self._validate_vector(vector,fingerprint); self.cache.put(item,fingerprint,vector); out[idx]=vector
                        return
                    except Exception as exc:
                        last=exc
                        if attempt>=self.max_retries: raise
                        await asyncio.sleep(0)
                raise last
        tasks=[]
        for entries in groups.values():
            for start in range(0,len(entries),self.max_batch_size): tasks.append(asyncio.create_task(run_batch(entries[start:start+self.max_batch_size])))
        await asyncio.gather(*tasks)
        return tuple(out)
    @staticmethod
    def _validate_vector(vector,fingerprint):
        if len(vector)!=fingerprint.dimension: raise ValueError("embedding dimension does not match fingerprint")

class QueryEmbeddingRuntime:
    """Conservative query embedding: query text is local-only by default."""
    def __init__(self,runtime:EmbeddingRuntime,fingerprint:EmbeddingFingerprint,destination:ProcessingDestination,query_labels_factory):
        self.runtime=runtime; self.fingerprint=fingerprint; self.destination=destination; self.query_labels_factory=query_labels_factory
    async def embed_query(self,query,scope):
        labels=self.query_labels_factory(scope)
        item=EmbeddingInput("query","query",query,"",labels)
        return (await self.runtime.embed((item,),scope,self.fingerprint,self.destination))[0]
