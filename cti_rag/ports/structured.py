from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Protocol, Tuple
from cti_rag.contracts import SnapshotManifestRef, TemporalRequest
from .capabilities import BackendCapabilities, ChannelResult
from .policy import EffectiveScope
@dataclass(frozen=True)
class StructuredQuerySpec:
    template_id:str; parameters:Tuple[Tuple[str,Any],...]
@dataclass(frozen=True)
class StructuredRequest:
    spec:StructuredQuerySpec; scope:EffectiveScope; temporal:TemporalRequest; snapshot:Optional[SnapshotManifestRef]=None; deadline:Optional[datetime]=None; cancellation_token:Optional[object]=None
class StructuredPort(Protocol):
    capabilities:BackendCapabilities
    async def execute(self,request:StructuredRequest)->ChannelResult: ...
