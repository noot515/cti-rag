"""Deterministic embedding fakes for contract tests only; not semantic quality evidence."""
from __future__ import annotations
import hashlib
from cti_rag.ports import BackendCapabilities

class DeterministicEmbeddingModel:
    def __init__(self,dimension=8,failures_before_success=0):
        self.dimension=dimension; self.failures_before_success=failures_before_success; self.calls=0; self.batch_sizes=[]; self.transferred_texts=[]; self.capabilities=BackendCapabilities(model_fingerprint=f"deterministic/{dimension}",max_batch_size=1024)
    def _vector(self,text):
        digest=hashlib.sha256(text.encode("utf-8")).digest()
        return tuple((digest[i]/127.5)-1.0 for i in range(self.dimension))
    async def invoke(self,request):
        self.calls+=1; self.batch_sizes.append(len(request.inputs)); self.transferred_texts.extend(str(v) for v in request.inputs)
        if self.calls<=self.failures_before_success: raise RuntimeError("synthetic transient embedding failure")
        return {"vectors":tuple(self._vector(str(v)) for v in request.inputs)}
