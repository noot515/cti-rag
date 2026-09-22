from dataclasses import dataclass
from typing import Protocol, Tuple
from cti_rag.contracts import IdentityAttribute, PolicyLabels, TemporalMetadata
from .source import SourceRecord
@dataclass(frozen=True)
class NormalizedRecord:
    stable_upstream_id:str; upstream_object_type:str; normalized_bytes:bytes; identity_attributes:Tuple[IdentityAttribute,...]
    temporal:TemporalMetadata; policy:PolicyLabels; content_schema_version:str; upstream_version:str|None=None
class Normalizer(Protocol):
    normalizer_fingerprint:str
    def normalize(self, record:SourceRecord)->NormalizedRecord: ...
