from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, Tuple
from .capabilities import BackendCapabilities
@dataclass(frozen=True)
class SourceRecord:
    record_key:str; raw_bytes:bytes; upstream_version:Optional[str]=None; claimed_digest:Optional[str]=None
@dataclass(frozen=True)
class SourcePage:
    records:Tuple[SourceRecord,...]; next_cursor:Optional[str]; exhausted:bool=False
@dataclass(frozen=True)
class SourceDeletion:
    stable_upstream_id:str; reason:str
class SourceConnector(Protocol):
    capabilities:BackendCapabilities
    source_id:str
    async def fetch_page(self,cursor:Optional[str],deadline:Optional[datetime]=None,cancellation_token:Optional[object]=None)->SourcePage: ...
