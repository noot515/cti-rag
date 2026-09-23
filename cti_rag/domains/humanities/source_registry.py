from dataclasses import dataclass
from enum import Enum
from typing import Optional,Tuple
class HumanitiesSourceStatus(str,Enum):FIXTURE_VALIDATED="fixture_validated";LIVE_VALIDATED="live_validated";DEFERRED="deferred";BLOCKED="blocked"
@dataclass(frozen=True)
class HumanitiesSourceCoverage:
    source_id:str;status:HumanitiesSourceStatus;format:str;reason:str="";connector:bool=False;normalizer:bool=False;source_uri:Optional[str]=None
HUMANITIES_SOURCE_COVERAGE=(
 HumanitiesSourceCoverage("gutenberg-public-domain-fixture",HumanitiesSourceStatus.FIXTURE_VALIDATED,"public-domain ebook JSON","small public-domain U.S. text fixture only; no live catalog/update crawl",True,True,"https://www.gutenberg.org/ebooks/1342"),
 HumanitiesSourceCoverage("tei-perseus-style-fixture",HumanitiesSourceStatus.FIXTURE_VALIDATED,"TEI XML","synthetic TEI/Perseus-style fixture; no live Perseus endpoint or redistribution claim",True,True,None),
 HumanitiesSourceCoverage("chronicling-america-iiif-fixture",HumanitiesSourceStatus.FIXTURE_VALIDATED,"IIIF/newspaper JSON","synthetic newspaper/IIIF metadata with LOC rights guidance; no live item harvest",True,True,"https://www.loc.gov/collections/chronicling-america/"),
 HumanitiesSourceCoverage("biglam",HumanitiesSourceStatus.DEFERRED,"aggregated library/archive metadata","source-specific rights, availability, and update contract not pinned"),
 HumanitiesSourceCoverage("dpla",HumanitiesSourceStatus.DEFERRED,"DPLA JSON-LD API","API key and item-level rights/source coverage not activated","",False,"https://pro.dp.la/developers/api-basics"),
 HumanitiesSourceCoverage("europeana",HumanitiesSourceStatus.DEFERRED,"Europeana EDM","per-object rights statements must be preserved; API/source lifecycle not activated",False,False,"https://pro.europeana.eu/page/available-rights-statements"),
 HumanitiesSourceCoverage("museums",HumanitiesSourceStatus.DEFERRED,"institution APIs/IIIF","institution-specific rights and schemas require separate manifests"),
 HumanitiesSourceCoverage("other-archives",HumanitiesSourceStatus.DEFERRED,"archive/IIIF/TEI","rights, provenance, language analyzer, and update semantics must be validated per archive"),
)
def humanities_source_coverage()->Tuple[HumanitiesSourceCoverage,...]:return HUMANITIES_SOURCE_COVERAGE
