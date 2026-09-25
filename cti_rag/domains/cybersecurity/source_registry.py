from dataclasses import dataclass
from enum import Enum
from typing import Optional,Tuple

class SourceAdapterStatus(str,Enum):
    IMPLEMENTED="implemented"; FIXTURE_VALIDATED="fixture_validated"; LIVE_VALIDATED="live_validated"; BLOCKED="blocked"; DEFERRED="deferred"

@dataclass(frozen=True)
class SourceCoverageEntry:
    source_id:str; status:SourceAdapterStatus; format:str; reason:str=""
    connector:bool=False; normalizer:bool=False; source_uri:Optional[str]=None

CORE_SOURCE_COVERAGE=(
    SourceCoverageEntry("mitre-attack-stix",SourceAdapterStatus.FIXTURE_VALIDATED,"STIX 2.1 bundle","offline real-format fixture; live network lifecycle not run",True,True,"https://attack.mitre.org/"),
    SourceCoverageEntry("cve-list-v5",SourceAdapterStatus.FIXTURE_VALIDATED,"CVE JSON 5.x","offline real-format fixture; live git/release lifecycle not run",True,True,"https://github.com/CVEProject/cvelistV5"),
    SourceCoverageEntry("cisa-kev",SourceAdapterStatus.FIXTURE_VALIDATED,"CISA KEV JSON","offline real-format fixture; live feed lifecycle not run",True,True,"https://www.cisa.gov/known-exploited-vulnerabilities-catalog"),
    SourceCoverageEntry("nvd",SourceAdapterStatus.DEFERRED,"NVD JSON/API","no pinned source-format fixture bundled in this phase"),
    SourceCoverageEntry("ghsa",SourceAdapterStatus.DEFERRED,"GitHub Security Advisory","no pinned source-format fixture bundled in this phase"),
    SourceCoverageEntry("cwe",SourceAdapterStatus.DEFERRED,"CWE XML/CSV","no pinned source-format fixture bundled in this phase"),
    SourceCoverageEntry("capec",SourceAdapterStatus.DEFERRED,"CAPEC XML","no pinned source-format fixture bundled in this phase"),
    SourceCoverageEntry("d3fend",SourceAdapterStatus.DEFERRED,"D3FEND ontology","manifest-only scope; adapter not claimed"),
    SourceCoverageEntry("atlas",SourceAdapterStatus.DEFERRED,"MITRE ATLAS","manifest-only scope; adapter not claimed"),
    SourceCoverageEntry("car",SourceAdapterStatus.DEFERRED,"MITRE CAR","manifest-only scope; adapter not claimed"),
    SourceCoverageEntry("attack-flow",SourceAdapterStatus.DEFERRED,"Attack Flow STIX","manifest-only scope; adapter not claimed"),
    SourceCoverageEntry("opencti-read",SourceAdapterStatus.FIXTURE_VALIDATED,"OpenCTI STIX 2.1 read API","read-only real-format fixtures validated; live OpenCTI credentials/service not supplied",True,True,None),
    SourceCoverageEntry("misp",SourceAdapterStatus.DEFERRED,"MISP JSON/STIX","requires deployment-specific source contract"),
    SourceCoverageEntry("reports-tram-sightings",SourceAdapterStatus.DEFERRED,"reports/TRAM/sightings","heterogeneous report family; no false shared adapter"),
    SourceCoverageEntry("sigma",SourceAdapterStatus.DEFERRED,"Sigma YAML","code/detection artifacts remain inert evidence"),
    SourceCoverageEntry("atomic-red-team",SourceAdapterStatus.DEFERRED,"Atomic YAML","execution content remains inert evidence"),
    SourceCoverageEntry("cvefixes",SourceAdapterStatus.DEFERRED,"CVEfixes dataset","large code dataset; no bulk ingest before lifecycle validation"),
    SourceCoverageEntry("megavul",SourceAdapterStatus.DEFERRED,"MegaVul dataset","large code dataset; no bulk ingest before lifecycle validation"),
    SourceCoverageEntry("poc-metadata",SourceAdapterStatus.DEFERRED,"PoC metadata","metadata only; retrieved code is never executable authority"),
    SourceCoverageEntry("soc-corpora",SourceAdapterStatus.DEFERRED,"SOC telemetry","large telemetry stays structured with selective summaries"),
)
def source_coverage_matrix()->Tuple[SourceCoverageEntry,...]:return CORE_SOURCE_COVERAGE
