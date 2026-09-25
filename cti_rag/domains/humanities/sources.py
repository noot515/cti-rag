from __future__ import annotations
import json,xml.etree.ElementTree as ET
from datetime import date,datetime,timedelta,timezone
from cti_rag.contracts import AccessLabel,AvailabilityBasis,HistoricalDate,HistoricalPrecision,IdentityAttribute,PolicyLabels,ProcessingClass,TemporalMetadata,canonical_json_bytes
from cti_rag.ingestion import SourceManifest
from cti_rag.ports import BackendCapabilities,NormalizedRecord,SourcePage,SourceRecord
from .analyzers import analyzer_profile
from .fixtures import GUTENBERG_ROWS,TEI_PERSEUS_STYLE_FIXTURE,IIIF_NEWSPAPER_FIXTURE

UTC=timezone.utc
PUBLIC=lambda license_id:PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,license_id=license_id,retention_class="standard")
def _dt(v):
    if v is None:return None
    return datetime.fromisoformat(str(v).replace("Z","+00:00")).astimezone(UTC)
def _historical(payload):
    if not payload:return None
    precision=str(payload.get("precision","uncertain"))
    mapping={
      "exact_date":HistoricalPrecision.EXACT_DATE,"month":HistoricalPrecision.MONTH,"year":HistoricalPrecision.YEAR,
      "approximate":HistoricalPrecision.APPROXIMATE,"range":HistoricalPrecision.RANGE,"uncertain":HistoricalPrecision.UNCERTAIN,
    }
    start=payload.get("start");end=payload.get("end_exclusive")
    if not start or not end:return None
    earliest=date.fromisoformat(start);latest=date.fromisoformat(end)-timedelta(days=1)
    return HistoricalDate(earliest,latest,mapping.get(precision,HistoricalPrecision.UNCERTAIN),payload.get("label"))
def _validate_alignment(p):
    original=str(p.get("original",""));normalized=str(p.get("normalized",""))
    rows=tuple(p.get("alignment",()))
    if not rows:raise ValueError("humanities passage requires alignment")
    for row in rows:
        os,oe,ns,ne=int(row["original_start"]),int(row["original_end"]),int(row["normalized_start"]),int(row["normalized_end"])
        confidence=float(row.get("confidence",1.0))
        if os<0 or oe<=os or ns<0 or ne<=ns or oe>len(original) or ne>len(normalized) or not 0<=confidence<=1:raise ValueError("invalid humanities alignment")
    return rows
def _validate_passages(passages):
    out=[]
    for p in passages:
        role=str(p.get("role",""))
        if role not in ("primary_text","editorial_annotation","scholarly_claim","interpretation"):raise ValueError("unsupported humanities passage role")
        language=str(p.get("language",""))
        profile=analyzer_profile(language)
        _validate_alignment(p)
        if role=="primary_text" and not str(p.get("original","")).strip():raise ValueError("primary text cannot be empty")
        out.append(dict(p,language=language,analyzer_supported=profile.supported,analyzer_version=profile.analyzer_version,analyzer_reason=profile.reason))
    return out

GUTENBERG_MANIFEST=SourceManifest(
 "gutenberg-public-domain-fixture","humanities","gutenberg-public-domain-json","humanities-object","fixture id+content digest","Project-Gutenberg-Public-Domain-US",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","immutable fixture revisions","explicit fixture replacement only",AvailabilityBasis.TRUSTED_ARCHIVE,
 ("exact","lexical","dense","graph","structured"),source_uri="https://www.gutenberg.org/ebooks/1342",
 license_notice="Ebook 1342 is marked public domain in the USA. Embedded text excludes Project Gutenberg license/trademark boilerplate; fixture redistribution is U.S.-scope only.",
 connector_fingerprint="gutenberg-fixture-connector/1",parser_fingerprint="gutenberg-humanities-normalizer/1")
TEI_MANIFEST=SourceManifest(
 "tei-perseus-style-fixture","humanities","tei-xml","humanities-edition","fixture id+content digest","public-domain-ancient-text-fixture",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","immutable TEI fixture","explicit fixture replacement only",AvailabilityBasis.TRUSTED_ARCHIVE,
 ("exact","lexical","dense","graph","structured"),source_uri="fixture:tei-perseus-style",
 license_notice="Synthetic TEI/Perseus-style markup around ancient public-domain text; no claim that the markup is an upstream Perseus record.",
 connector_fingerprint="tei-fixture-connector/1",parser_fingerprint="tei-humanities-normalizer/1")
IIIF_MANIFEST=SourceManifest(
 "chronicling-america-iiif-fixture","humanities","iiif-newspaper-json","humanities-edition","fixture id+content digest","LOC-Chronicling-America-Rights-Statement",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","immutable IIIF metadata fixture","explicit fixture replacement only",AvailabilityBasis.TRUSTED_ARCHIVE,
 ("exact","lexical","dense","graph","structured"),source_uri="https://www.loc.gov/collections/chronicling-america/",
 license_notice="Synthetic newspaper text and IIIF metadata modeled on Chronicling America. LOC states the collection is believed public domain/no known restrictions; item-level rights still require review.",
 connector_fingerprint="iiif-fixture-connector/1",parser_fingerprint="iiif-humanities-normalizer/1")

class TupleConnector:
    capabilities=BackendCapabilities(pagination=True,cancellation=True,max_batch_size=1000)
    def __init__(self,source_id,rows):self.source_id=source_id;self.rows=tuple(rows);self.connector_fingerprint=f"{source_id}-connector/1"
    async def fetch_page(self,cursor=None,deadline=None,cancellation_token=None):
        start=int(cursor or 0);records=[]
        for row in self.rows:
            raw=row if isinstance(row,bytes) else canonical_json_bytes(row)
            if isinstance(row,bytes):
                root=ET.fromstring(row);key=root.attrib.get("edition_id","tei-record");version="tei-1"
            else:key=str(row.get("id","missing"));version=str(row.get("version","v1"))
            records.append(SourceRecord(key,raw,version))
        return SourcePage(tuple(records[start:]),None,True)
def GutenbergConnector(rows=GUTENBERG_ROWS):return TupleConnector(GUTENBERG_MANIFEST.source_id,rows)
def TeiConnector(rows=(TEI_PERSEUS_STYLE_FIXTURE,)):return TupleConnector(TEI_MANIFEST.source_id,rows)
def IiifConnector(rows=(IIIF_NEWSPAPER_FIXTURE,)):return TupleConnector(IIIF_MANIFEST.source_id,rows)

class GutenbergNormalizer:
    normalizer_fingerprint="gutenberg-humanities-normalizer/1"
    def normalize(self,record):
        d=json.loads(record.raw_bytes.decode());kind=d.get("record_type")
        if kind not in ("work","edition"):raise ValueError("unsupported gutenberg fixture record type")
        stable=str(d.get("id",""));available=_dt(d.get("available_at"))
        if not stable or available is None:raise ValueError("gutenberg fixture identity/availability required")
        normalized=dict(d,kind=kind)
        if kind=="edition":
            normalized["passages"]=_validate_passages(d.get("passages",()))
        hist=_historical(d.get("date_interval"))
        temporal=TemporalMetadata(available,available,published_at=hist,available_at=available,available_at_basis=AvailabilityBasis.TRUSTED_ARCHIVE,valid_from=hist)
        attrs=(IdentityAttribute("humanities_id",stable),)
        return NormalizedRecord(stable,f"humanities-{kind}",canonical_json_bytes(normalized),attrs,temporal,PUBLIC(GUTENBERG_MANIFEST.license_id),f"humanities-{kind}/1",record.upstream_version)

class TeiNormalizer:
    normalizer_fingerprint="tei-humanities-normalizer/1"
    def normalize(self,record):
        try:root=ET.fromstring(record.raw_bytes)
        except Exception as exc:raise ValueError("invalid TEI XML") from exc
        edition_id=str(root.attrib.get("edition_id",""));work_id=str(root.attrib.get("work_id",""));witness_id=str(root.attrib.get("witness_id",""));language=str(root.attrib.get("language",""))
        if not edition_id or not work_id or not witness_id or not language:raise ValueError("TEI fixture identity fields required")
        available=_dt(root.attrib.get("available_at"))
        passages=[]
        for i,node in enumerate(root.findall(".//l"),1):
            cid=node.attrib.get("{http://www.w3.org/XML/1998/namespace}id") or f"PASSAGE:{edition_id}:{i}"
            text=" ".join("".join(node.itertext()).split())
            passages.append({"id":cid,"role":"primary_text","ordinal":i,"original":text,"normalized":text,"language":language,"transcription_quality":"manual",
              "locator":{"kind":"tei","xpath":f"/TEI/text/body/div/l[{i}]","canonical_id":cid},"alignment":[{"original_start":0,"original_end":len(text),"normalized_start":0,"normalized_end":len(text),"confidence":1.0}]})
        for i,node in enumerate(root.findall(".//note"),1):
            text=" ".join("".join(node.itertext()).split())
            passages.append({"id":f"ANNOTATION:{edition_id}:{i}","role":"editorial_annotation","ordinal":100+i,"original":text,"normalized":text,"language":language,"transcription_quality":"editorial",
              "locator":{"kind":"tei","xpath":f"/TEI/text/body/div/note[{i}]"},"alignment":[{"original_start":0,"original_end":len(text),"normalized_start":0,"normalized_end":len(text),"confidence":1.0}]})
        translation=root.find(".//translation");translation_data=None
        if translation is not None:
            seg=translation.find("seg");text="" if seg is None else " ".join("".join(seg.itertext()).split())
            translation_data={"edition_id":translation.attrib.get("edition_id"),"source_edition":translation.attrib.get("source_edition"),"language":translation.attrib.get("language"),"text":text,
              "locator":{"kind":"tei","xpath":"/TEI/translation/seg[1]"}}
        normalized={"kind":"edition","id":edition_id,"work_id":work_id,"witness_id":witness_id,"label":"Aeneid TEI fixture","language":language,"rights":root.attrib.get("rights"),
                    "date_interval":{"precision":"uncertain","label":"ancient source date not converted to a modern instant"},"available_at":root.attrib.get("available_at"),
                    "passages":_validate_passages(passages),"translation":translation_data}
        temporal=TemporalMetadata(available,available,available_at=available,available_at_basis=AvailabilityBasis.TRUSTED_ARCHIVE)
        return NormalizedRecord(edition_id,"humanities-edition",canonical_json_bytes(normalized),(IdentityAttribute("edition_id",edition_id),IdentityAttribute("work_id",work_id)),temporal,PUBLIC(TEI_MANIFEST.license_id),"tei-document/1",record.upstream_version)

class IiifNormalizer:
    normalizer_fingerprint="iiif-humanities-normalizer/1"
    def normalize(self,record):
        d=json.loads(record.raw_bytes.decode())
        if d.get("record_type")!="newspaper":raise ValueError("unsupported IIIF fixture record type")
        for key in ("id","work_id","article_id","page_id","institution_id","canvas_id","page","rights","available_at"):
            if d.get(key) in (None,""):raise ValueError(f"IIIF fixture missing {key}")
        available=_dt(d["available_at"]);passages=[]
        for p in _validate_passages(d.get("passages",())):
            locator={"kind":"iiif","canvas_id":d["canvas_id"],"page":int(d["page"]),"bbox":tuple(float(v) for v in d.get("bbox",()))}
            passages.append(dict(p,locator=locator))
        normalized={"kind":"edition","id":d["id"],"work_id":d["work_id"],"article_id":d["article_id"],"page_id":d["page_id"],"institution_id":d["institution_id"],
                    "label":d["label"],"language":d["language"],"rights":d["rights"],"rights_statement":d.get("rights_statement"),"date_interval":d["date_interval"],
                    "available_at":d["available_at"],"passages":passages,"edition_type":"newspaper"}
        hist=_historical(d.get("date_interval"))
        temporal=TemporalMetadata(available,available,published_at=hist,available_at=available,available_at_basis=AvailabilityBasis.TRUSTED_ARCHIVE,valid_from=hist)
        return NormalizedRecord(d["id"],"humanities-edition",canonical_json_bytes(normalized),(IdentityAttribute("edition_id",d["id"]),IdentityAttribute("work_id",d["work_id"])),temporal,PUBLIC(IIIF_MANIFEST.license_id),"iiif-newspaper/1",record.upstream_version)
