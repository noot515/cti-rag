from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, Tuple
from cti_rag.contracts import SnapshotManifestRef, TemporalRequest
from .capabilities import BackendCapabilities, ChannelResult
from .policy import EffectiveScope

@dataclass(frozen=True)
class GraphRequest:
    seeds:Tuple[str,...]
    relations:Tuple[str,...]
    scope:EffectiveScope
    temporal:TemporalRequest
    max_hops:int=2
    max_paths:int=100
    snapshot:Optional[SnapshotManifestRef]=None
    deadline:Optional[datetime]=None
    cancellation_token:Optional[object]=None
    template_id:str="supported-relations"
    max_seeds:int=8
    max_degree:int=20
    max_examined_edges:int=500
    def __post_init__(self):
        if not self.seeds: raise ValueError("graph request requires at least one seed")
        if self.max_hops<1 or self.max_hops>2: raise ValueError("graph max_hops must be in [1,2]")
        if self.max_paths<=0 or self.max_seeds<=0 or self.max_degree<=0 or self.max_examined_edges<=0: raise ValueError("graph traversal limits must be positive")
        if len(self.seeds)>self.max_seeds: raise ValueError("graph seed limit exceeded")
        if not self.template_id.strip(): raise ValueError("graph template_id required")
class GraphPort(Protocol):
    capabilities:BackendCapabilities
    async def traverse(self,request:GraphRequest)->ChannelResult: ...
