from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional, Union
from .errors import ValidationError
class AvailabilityBasis(str,Enum):
    UNKNOWN="unknown"; SOURCE_PUBLISHED="source_published"; UPSTREAM_METADATA="upstream_metadata"; TRUSTED_ARCHIVE="trusted_archive"; FIRST_OBSERVED="first_observed"; CONSERVATIVE_BOUND="conservative_bound"
class HistoricalPrecision(str,Enum):
    EXACT_DATE="exact_date"; MONTH="month"; YEAR="year"; APPROXIMATE="approximate"; RANGE="range"; UNCERTAIN="uncertain"
class TemporalMode(str,Enum):
    CURRENT="current"; HISTORICAL_PUBLIC="historical_public"; HISTORICAL_SYSTEM_REPLAY="historical_system_replay"
def ensure_utc(v:datetime)->datetime:
    if v.tzinfo is None or v.utcoffset() is None: raise ValidationError("timestamps must include an explicit UTC offset")
    return v.astimezone(timezone.utc)
@dataclass(frozen=True)
class HistoricalDate:
    earliest:date; latest:date; precision:HistoricalPrecision; label:Optional[str]=None
    def __post_init__(self):
        if self.latest<self.earliest: raise ValidationError("historical range reversed")
@dataclass(frozen=True)
class TemporalMetadata:
    first_observed_at:datetime; recorded_from:datetime; published_at:Optional[Union[datetime,HistoricalDate]]=None; available_at:Optional[datetime]=None; available_at_basis:AvailabilityBasis=AvailabilityBasis.UNKNOWN; valid_from:Optional[Union[datetime,HistoricalDate]]=None; valid_to:Optional[Union[datetime,HistoricalDate]]=None; recorded_to:Optional[datetime]=None
    def __post_init__(self):
        ensure_utc(self.first_observed_at); ensure_utc(self.recorded_from)
        if isinstance(self.published_at,datetime): ensure_utc(self.published_at)
        if self.available_at is not None: ensure_utc(self.available_at)
        if isinstance(self.valid_from,datetime): ensure_utc(self.valid_from)
        if isinstance(self.valid_to,datetime): ensure_utc(self.valid_to)
        if self.recorded_to is not None: ensure_utc(self.recorded_to)
        if self.available_at is None and self.available_at_basis!=AvailabilityBasis.UNKNOWN: raise ValidationError("availability basis without available_at")
        if self.available_at is not None and self.available_at_basis==AvailabilityBasis.UNKNOWN: raise ValidationError("available_at requires basis")
