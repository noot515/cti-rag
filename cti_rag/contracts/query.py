from dataclasses import dataclass
from typing import Optional, Tuple
from .errors import ValidationError
from .policy import AccessLabel
from .temporal import TemporalMode
@dataclass(frozen=True)
class EvidenceScope:
    tenant_id:str; domains:Tuple[str,...]; source_ids:Tuple[str,...]=(); access_labels:Tuple[AccessLabel,...]=(AccessLabel.PUBLIC,)
    def __post_init__(self):
        if not self.tenant_id.strip() or not self.domains: raise ValidationError("scope requires tenant and domains")
@dataclass(frozen=True)
class CandidateBudget:
    total:int; exact:Optional[int]=None; lexical:Optional[int]=None; dense:Optional[int]=None; graph:Optional[int]=None; structured:Optional[int]=None
    def __post_init__(self):
        if self.total<=0: raise ValidationError("budget total must be positive")
@dataclass(frozen=True)
class TemporalRequest:
    mode:TemporalMode; cutoff_iso:Optional[str]=None; snapshot_manifest_id:Optional[str]=None
    def __post_init__(self):
        if self.mode==TemporalMode.HISTORICAL_PUBLIC and self.cutoff_iso is None: raise ValidationError("historical_public requires cutoff")
        if self.mode==TemporalMode.HISTORICAL_SYSTEM_REPLAY and self.snapshot_manifest_id is None: raise ValidationError("system replay requires snapshot")
