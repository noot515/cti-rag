from dataclasses import dataclass
from enum import Enum
from typing import Optional,Tuple
class NetworkingSourceStatus(str,Enum):FIXTURE_VALIDATED="fixture_validated";LIVE_VALIDATED="live_validated";DEFERRED="deferred";BLOCKED="blocked"
@dataclass(frozen=True)
class NetworkingSourceCoverage:
    source_id:str;status:NetworkingSourceStatus;format:str;reason:str="";connector:bool=False;normalizer:bool=False;source_uri:Optional[str]=None
NETWORKING_SOURCE_COVERAGE=(
 NetworkingSourceCoverage("rfc-editor",NetworkingSourceStatus.FIXTURE_VALIDATED,"RFC XML/document","pinned offline document fixtures; live RFC index/download reconciliation not run",True,True,"https://www.rfc-editor.org/"),
 NetworkingSourceCoverage("ripe-ris-fixture",NetworkingSourceStatus.FIXTURE_VALIDATED,"BGP observation JSON","small pinned collector fixtures; no live RIS stream claimed",True,True,"https://ris.ripe.net/"),
 NetworkingSourceCoverage("rpki-roa-fixture",NetworkingSourceStatus.FIXTURE_VALIDATED,"RPKI ROA JSON","offline authorization fixtures; no live repository/validator lifecycle",True,True,"https://rpki-validator.ripe.net/"),
 NetworkingSourceCoverage("dns-observation-fixture",NetworkingSourceStatus.FIXTURE_VALIDATED,"DNS observation JSON","synthetic time/vantage fixtures only",True,True,None),
 NetworkingSourceCoverage("rdap-registration-fixture",NetworkingSourceStatus.FIXTURE_VALIDATED,"RDAP registration JSON","synthetic registration fixture only",True,True,None),
 NetworkingSourceCoverage("rir-bulk-registration",NetworkingSourceStatus.DEFERRED,"RIR delegated/registration","RDAP fixture covers semantics; bulk source not activated"),
 NetworkingSourceCoverage("network-configurations",NetworkingSourceStatus.DEFERRED,"device configuration","deployment-specific access and secrets policy required"),
 NetworkingSourceCoverage("packet-event-metadata",NetworkingSourceStatus.DEFERRED,"packet/event metadata","high-volume/private telemetry requires separate scope and retention"),
 NetworkingSourceCoverage("certificate-observations",NetworkingSourceStatus.DEFERRED,"certificate metadata","source/licensing/update contract not pinned"),
 NetworkingSourceCoverage("network-topology",NetworkingSourceStatus.DEFERRED,"topology","topology is source-specific and must not be inferred as ownership"),
)
def networking_source_coverage()->Tuple[NetworkingSourceCoverage,...]:return NETWORKING_SOURCE_COVERAGE
