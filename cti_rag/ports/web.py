"""Backend-neutral web discovery and captured-evidence ports."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional,Protocol,Tuple
from cti_rag.contracts import PolicyLabels,ProvenanceRef
from .policy import EffectiveScope

class WebStatus(str,Enum):
    OK="ok";EMPTY="empty";DISABLED="disabled";DENIED="denied";UNAVAILABLE="unavailable";REJECTED="rejected"

@dataclass(frozen=True)
class SearchProviderRequest:
    query:str;scope:EffectiveScope;labels:PolicyLabels;max_results:int=5;purpose:str="web_search"
    def __post_init__(self):
        if not self.query.strip() or self.max_results<=0:raise ValueError("web discovery requires a non-empty query and positive result limit")

@dataclass(frozen=True)
class DiscoveryItem:
    provider:str;url:str;title:str;snippet:str;rank:int
    def __post_init__(self):
        if not self.provider.strip() or not self.url.strip() or self.rank<1:raise ValueError("discovery item requires provider, URL, and one-based rank")
    @property
    def citable(self):return False

@dataclass(frozen=True)
class DiscoveryResult:
    status:WebStatus;items:Tuple[DiscoveryItem,...]=();reason:Optional[str]=None
    def __post_init__(self):
        if self.status==WebStatus.OK and not self.items:raise ValueError("ok discovery result requires items")
        if self.status!=WebStatus.OK and self.items:raise ValueError("non-ok discovery result cannot expose items")

@dataclass(frozen=True)
class FetchRequest:
    url:str;scope:EffectiveScope;labels:PolicyLabels;purpose:str="web_fetch"
    def __post_init__(self):
        if not self.url.strip():raise ValueError("fetch request requires URL")

@dataclass(frozen=True)
class CapturedWebEvidence:
    capture_id:str;revision_uid:str;requested_url:str;final_url:str;content_type:str;raw_bytes:bytes;text:str;content_digest:str
    fetched_at:datetime;available_at:datetime;provenance:ProvenanceRef;labels:PolicyLabels;untrusted_content:bool=True;redirect_chain:Tuple[str,...]=()
    @property
    def citable(self):return bool(self.text) and self.provenance.revision_uid==self.revision_uid

@dataclass(frozen=True)
class FetchResult:
    status:WebStatus;evidence:Optional[CapturedWebEvidence]=None;reason:Optional[str]=None
    def __post_init__(self):
        if self.status==WebStatus.OK and self.evidence is None:raise ValueError("ok fetch result requires captured evidence")
        if self.status!=WebStatus.OK and self.evidence is not None:raise ValueError("non-ok fetch result cannot expose evidence")

class SearchProvider(Protocol):
    async def discover(self,request:SearchProviderRequest)->DiscoveryResult:...
class FetchPort(Protocol):
    async def fetch(self,request:FetchRequest)->FetchResult:...
