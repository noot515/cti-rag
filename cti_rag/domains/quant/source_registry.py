from dataclasses import dataclass
from enum import Enum
from typing import Optional,Tuple
class QuantSourceStatus(str,Enum):FIXTURE_VALIDATED="fixture_validated";LIVE_VALIDATED="live_validated";DEFERRED="deferred";BLOCKED="blocked"
@dataclass(frozen=True)
class QuantSourceCoverage:
    source_id:str;status:QuantSourceStatus;format:str;reason:str="";connector:bool=False;normalizer:bool=False;source_uri:Optional[str]=None
QUANT_SOURCE_COVERAGE=(
 QuantSourceCoverage("sec-edgar-fixture",QuantSourceStatus.FIXTURE_VALIDATED,"SEC filing/XBRL-shaped JSON","offline filing/company fixture only; live EDGAR lifecycle and rate policies not run",True,True,"https://www.sec.gov/edgar/sec-api-documentation"),
 QuantSourceCoverage("fred-alfred-fixture",QuantSourceStatus.FIXTURE_VALIDATED,"FRED/ALFRED observation JSON","offline vintage fixture only; no live API credential/network lifecycle",True,True,"https://fred.stlouisfed.org/docs/api/fred/"),
 QuantSourceCoverage("licensed-price-file-fixture",QuantSourceStatus.FIXTURE_VALIDATED,"licensed price CSV file","file-import mechanics validated only; no entitlement to a production market feed",True,True,None),
 QuantSourceCoverage("licensed-corporate-action-file-fixture",QuantSourceStatus.FIXTURE_VALIDATED,"licensed corporate-action CSV file","file-import mechanics validated only; no production feed entitlement",True,True,None),
 QuantSourceCoverage("security-master-fixture",QuantSourceStatus.FIXTURE_VALIDATED,"security master JSON","ticker/exchange/interval and delisting fixture only",True,True,None),
 QuantSourceCoverage("fundamentals",QuantSourceStatus.FIXTURE_VALIDATED,"SEC/XBRL facts","covered by SEC filing fixture; live provider coverage not claimed"),
 QuantSourceCoverage("earnings-material",QuantSourceStatus.DEFERRED,"earnings releases/transcripts","source, rights, and timing contract not pinned"),
 QuantSourceCoverage("disclosures",QuantSourceStatus.FIXTURE_VALIDATED,"SEC filing document sections","offline SEC-shaped disclosure fixture only"),
 QuantSourceCoverage("research",QuantSourceStatus.DEFERRED,"licensed/public research","rights, provider coverage, and point-in-time availability contract not pinned"),
)
def quant_source_coverage()->Tuple[QuantSourceCoverage,...]:return QUANT_SOURCE_COVERAGE
