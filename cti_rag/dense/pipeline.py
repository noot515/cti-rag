"""Dense projection build pipeline over authorized embedding generation."""
from __future__ import annotations
from cti_rag.contracts import namespaced_uid
from cti_rag.ports import ProjectionBuildRequest
from .models import DenseVectorRecord

class DenseIndexer:
    def __init__(self,embedding_runtime,builder,fingerprint,destination):
        self.embedding_runtime=embedding_runtime; self.builder=builder; self.fingerprint=fingerprint; self.destination=destination
    async def build(self,request:ProjectionBuildRequest,documents,scope):
        docs=tuple(documents)
        vectors=await self.embedding_runtime.embed(tuple(d.embedding_input() for d in docs),scope,self.fingerprint,self.destination)
        records=[]
        for doc,vector in zip(docs,vectors):
            rep_uid=namespaced_uid("rep","dense.representation",{"passage_uid":doc.passage_uid,"embedding_fingerprint":self.fingerprint.fingerprint_id})
            records.append(DenseVectorRecord(doc.passage_uid,doc.revision_uid,doc.object_uid,doc.domain,doc.source_id,doc.tenant_id,doc.access_label,doc.available_at,doc.valid_from,doc.valid_to,doc.locator_json,doc.original_text,tuple(vector),rep_uid,self.fingerprint.fingerprint_id))
        return self.builder.build(request,tuple(records),self.fingerprint)
