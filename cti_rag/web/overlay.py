"""Bounded request-local external discovery and capture orchestration."""
from __future__ import annotations
from cti_rag.ports.web import FetchRequest,SearchProviderRequest,WebStatus
from .models import EvidenceWithLiveOverlay,LiveEvidenceOverlay

class WebOverlayService:
    def __init__(self,*,provider=None,fetcher=None,enabled=False,max_fetches=3):
        if max_fetches<0:raise ValueError("max_fetches cannot be negative")
        self.provider=provider;self.fetcher=fetcher;self.enabled=enabled;self.max_fetches=max_fetches
    async def augment(self,*,base_response,query,scope,labels):
        base_snapshot=base_response.snapshot.manifest_id
        if not self.enabled:return EvidenceWithLiveOverlay(base_response,LiveEvidenceOverlay(base_snapshot,status=WebStatus.DISABLED,reason="live overlay disabled"))
        if self.provider is None or self.fetcher is None:return EvidenceWithLiveOverlay(base_response,LiveEvidenceOverlay(base_snapshot,status=WebStatus.UNAVAILABLE,reason="web integration not configured"))
        discovery=await self.provider.discover(SearchProviderRequest(query,scope,labels,max(1,self.max_fetches)))
        if discovery.status!=WebStatus.OK:return EvidenceWithLiveOverlay(base_response,LiveEvidenceOverlay(base_snapshot,status=discovery.status,reason=discovery.reason))
        captures=[];failures=[]
        for item in discovery.items[:self.max_fetches]:
            result=await self.fetcher.fetch(FetchRequest(item.url,scope,labels))
            if result.status==WebStatus.OK:captures.append(result.evidence)
            else:failures.append(result.reason or result.status.value)
        status=WebStatus.OK if captures else (WebStatus.REJECTED if failures else WebStatus.EMPTY)
        reason=None if captures else ("; ".join(failures) if failures else "no captured sources")
        return EvidenceWithLiveOverlay(base_response,LiveEvidenceOverlay(base_snapshot,discovery.items,tuple(captures),status,reason))
