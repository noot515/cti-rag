"""Request-local live overlay contracts and explicit ingestion bridge."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional,Tuple
from cti_rag.contracts import namespaced_uid
from cti_rag.ports.web import CapturedWebEvidence,DiscoveryItem,WebStatus
from cti_rag.ports.source import SourcePage,SourceRecord

@dataclass(frozen=True)
class LiveEvidenceOverlay:
    base_snapshot_manifest_id:str
    discoveries:Tuple[DiscoveryItem,...]=()
    captures:Tuple[CapturedWebEvidence,...]=()
    status:WebStatus=WebStatus.EMPTY
    reason:Optional[str]=None
    overlay_id:Optional[str]=None
    def __post_init__(self):
        if not self.base_snapshot_manifest_id.strip():raise ValueError("live overlay requires the pinned base snapshot id")
        if self.overlay_id is None:
            object.__setattr__(self,"overlay_id",namespaced_uid("ovl","web.live",{"base":self.base_snapshot_manifest_id,"discoveries":tuple((d.provider,d.url,d.rank) for d in self.discoveries),"captures":tuple(c.revision_uid for c in self.captures)}))
    @property
    def layer(self):return "live_overlay"

@dataclass(frozen=True)
class EvidenceWithLiveOverlay:
    base:object
    live_overlay:LiveEvidenceOverlay
    @property
    def base_layer(self):return "pinned_snapshot"

class CapturedOverlayConnector:
    """Explicit bridge into ordinary ingestion; query handlers never persist directly."""
    def __init__(self,source_id:str,captures:Tuple[CapturedWebEvidence,...]):
        if not source_id.strip():raise ValueError("overlay connector requires source_id")
        self.source_id=source_id;self._captures=tuple(captures);self.capabilities=None
    async def fetch_page(self,cursor=None,deadline=None,cancellation_token=None):
        if cursor not in (None,"0"):return SourcePage((),None,exhausted=True)
        records=tuple(SourceRecord(record_key=c.final_url,raw_bytes=c.raw_bytes,upstream_version=c.revision_uid,claimed_digest=c.content_digest) for c in self._captures)
        return SourcePage(records,None,exhausted=True)
