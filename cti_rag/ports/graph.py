from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, Tuple
from cti_rag.contracts import SnapshotManifestRef, TemporalRequest
from .capabilities import BackendCapabilities, ChannelResult
from .policy import EffectiveScope
@dataclass(frozen=True)
class GraphRequest:
    seeds:Tuple[str,...]; relations:Tuple[str,...]; scope:EffectiveScope; temporal:TemporalRequest; max_hops:int=2; max_paths:int=100
    snapshot:Optional[SnapshotManifestRef]=None; deadline:Optional[datetime]=None; cancellation_token:Optional[object]=None
class GraphPort(Protocol):
    capabilities:BackendCapabilities
    async def traverse(self,request:GraphRequest)->ChannelResult: ...
