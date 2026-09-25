from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Protocol
from cti_rag.contracts import CandidateBudget, SnapshotManifestRef, TemporalRequest
from .capabilities import BackendCapabilities, ChannelResult
from .policy import EffectiveScope

class SearchKind(str,Enum): EXACT="exact"; LEXICAL="lexical"; DENSE="dense"
@dataclass(frozen=True)
class SearchRequest:
    query:str; kind:SearchKind; scope:EffectiveScope; temporal:TemporalRequest; budget:CandidateBudget
    snapshot:Optional[SnapshotManifestRef]=None; deadline:Optional[datetime]=None; cancellation_token:Optional[object]=None
    required_filters:frozenset[str]=frozenset()
class SearchPort(Protocol):
    capabilities: BackendCapabilities
    async def search(self, request: SearchRequest) -> ChannelResult: ...
