from __future__ import annotations
import csv,io,json
from datetime import datetime,timezone
from cti_rag.contracts import AccessLabel,AvailabilityBasis,IdentityAttribute,PolicyLabels,ProcessingClass,TemporalMetadata,canonical_json_bytes
from cti_rag.ingestion import SourceManifest
from cti_rag.ports import BackendCapabilities,NormalizedRecord,SourcePage,SourceRecord
from .fixtures import SEC_COMPANY_FIXTURE,SEC_FILING_FIXTURE,SEC_FILING_AMENDED_FIXTURE,FRED_ALFRED_FIXTURE,PRICE_CSV_FIXTURE,CORPORATE_ACTION_CSV_FIXTURE,SECURITY_MASTER_FIXTURE
UTC=timezone.utc
KNOWN_UNITS={"USD","shares","USD/shares","percent","index"}
def _dt(v):
    if v is None:return None
    if len(str(v))==10:v=str(v)+"T00:00:00Z"
    return datetime.fromisoformat(str(v).replace("Z","+00:00")).astimezone(UTC)
PUBLIC=lambda license_id:PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,license_id=license_id,retention_class="standard")

SEC_MANIFEST=SourceManifest("sec-edgar-fixture","quant","sec-filing-xbrl-json","sec-object","accession/content-digest","SEC-Public-Data",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","filings and amendments append","withdrawal/correction through explicit source revision",AvailabilityBasis.UPSTREAM_METADATA,
 ("exact","lexical","dense","structured","graph"),source_uri="https://www.sec.gov/edgar/sec-api-documentation",license_notice="Offline SEC-shaped fixtures only; SEC source headers/policies must be honored by any live connector.",connector_fingerprint="sec-fixture-connector/1",parser_fingerprint="sec-fixture-normalizer/1")
FRED_MANIFEST=SourceManifest("fred-alfred-fixture","quant","fred-alfred-observation-json","macro-observation","series/date/vintage","FRED-Terms",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","append observation vintages","source revision/vintage replacement",AvailabilityBasis.UPSTREAM_METADATA,
 ("structured",),source_uri="https://fred.stlouisfed.org/docs/api/fred/",license_notice="Offline FRED/ALFRED-shaped fixture; live API access/terms not claimed.",connector_fingerprint="fred-alfred-connector/1",parser_fingerprint="fred-alfred-normalizer/1")
PRICE_MANIFEST=SourceManifest("licensed-price-file-fixture","quant","licensed-price-csv","market-price","security/date/provider+file revision","TEST-LICENSE",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","file import revisions","explicit corrected/adjusted replacement",AvailabilityBasis.UPSTREAM_METADATA,
 ("structured",),source_uri="fixture:licensed-prices",license_notice="Synthetic licensed-file fixture only; no market-feed entitlement or production license is implied.",connector_fingerprint="licensed-price-file-connector/1",parser_fingerprint="licensed-price-normalizer/1")
ACTION_MANIFEST=SourceManifest("licensed-corporate-action-file-fixture","quant","licensed-corporate-action-csv","corporate-action","security/effective/action+file revision","TEST-LICENSE",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","file import revisions","explicit correction/removal",AvailabilityBasis.UPSTREAM_METADATA,
 ("structured",),source_uri="fixture:licensed-corporate-actions",license_notice="Synthetic corporate-action file fixture only.",connector_fingerprint="corporate-action-file-connector/1",parser_fingerprint="corporate-action-normalizer/1")
SECURITY_MASTER_MANIFEST=SourceManifest("security-master-fixture","quant","security-master-json","security-alias","security/ticker/exchange/interval","TEST-LICENSE",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","append alias/listing intervals","interval closure/correction",AvailabilityBasis.UPSTREAM_METADATA,
 ("structured","graph"),source_uri="fixture:security-master",license_notice="Synthetic security-master fixture; tickers are time-bounded aliases, not issuer identity.",connector_fingerprint="security-master-connector/1",parser_fingerprint="security-master-normalizer/1")

class JsonTupleConnector:
    capabilities=BackendCapabilities(pagination=True,cancellation=True,max_batch_size=1000)
    def __init__(self,source_id,rows):self.source_id=source_id;self.rows=tuple(rows);self.connector_fingerprint=f"{source_id}-connector/1"
    async def fetch_page(self,cursor=None,deadline=None,cancellation_token=None):
        start=int(cursor or 0);records=[]
        for row in self.rows:
            key=str(row.get("accessionNumber") or row.get("cik") or row.get("id") or "record")
            version=str(row.get("version") or row.get("acceptanceDateTime") or row.get("available_at") or "v1")
            records.append(SourceRecord(key,canonical_json_bytes(row),version))
        return SourcePage(tuple(records[start:]),None,True)
def SecConnector(rows=(SEC_COMPANY_FIXTURE,SEC_FILING_FIXTURE,SEC_FILING_AMENDED_FIXTURE)):return JsonTupleConnector(SEC_MANIFEST.source_id,rows)
def SecurityMasterConnector(rows=SECURITY_MASTER_FIXTURE):return JsonTupleConnector(SECURITY_MASTER_MANIFEST.source_id,rows)

class FredAlfredConnector:
    source_id=FRED_MANIFEST.source_id;connector_fingerprint="fred-alfred-connector/1";capabilities=BackendCapabilities(pagination=True,cancellation=True,max_batch_size=1000)
    def __init__(self,payload=FRED_ALFRED_FIXTURE):self.payload=payload
    async def fetch_page(self,cursor=None,deadline=None,cancellation_token=None):
        rows=[]
        for obs in self.payload["observations"]:
            body={k:self.payload[k] for k in ("series_id","title","units","frequency","seasonal_adjustment")}|dict(obs)
            rows.append(SourceRecord(f"{self.payload['series_id']}|{obs['date']}|{obs['realtime_start']}",canonical_json_bytes(body),obs["realtime_start"]))
        return SourcePage(tuple(rows),None,True)

class CsvFileConnector:
    capabilities=BackendCapabilities(pagination=True,cancellation=True,max_batch_size=10000)
    def __init__(self,source_id,raw_bytes,key_fields,version_fields):self.source_id=source_id;self.raw_bytes=raw_bytes;self.key_fields=tuple(key_fields);self.version_fields=tuple(version_fields);self.connector_fingerprint=f"{source_id}-connector/1"
    async def fetch_page(self,cursor=None,deadline=None,cancellation_token=None):
        reader=csv.DictReader(io.StringIO(self.raw_bytes.decode()));out=[]
        for row in reader:
            key="|".join(str(row[k]) for k in self.key_fields);version="|".join(str(row.get(k,"")) for k in self.version_fields)
            out.append(SourceRecord(key,canonical_json_bytes(row),version))
        return SourcePage(tuple(out),None,True)
def PriceFileConnector(raw_bytes=PRICE_CSV_FIXTURE):return CsvFileConnector(PRICE_MANIFEST.source_id,raw_bytes,("security_id","trading_date","provider"),("available_at","corporate_action_version"))
def CorporateActionFileConnector(raw_bytes=CORPORATE_ACTION_CSV_FIXTURE):return CsvFileConnector(ACTION_MANIFEST.source_id,raw_bytes,("security_id","action_type","effective_date","provider"),("available_at",))

class SecNormalizer:
    normalizer_fingerprint="sec-fixture-normalizer/1"
    def normalize(self,record):
        try:d=json.loads(record.raw_bytes.decode())
        except Exception as exc:raise ValueError("invalid_sec_json") from exc
        kind=d.get("record_type")
        if kind=="company":
            cik=str(d.get("cik",""))
            if len(cik)!=10 or not cik.isdigit():raise ValueError("sec_invalid_cik")
            available=_dt(d["available_at"]);norm={"kind":"sec-company","id":cik,"cik":cik,"name":str(d.get("name","")).strip(),"available_at":d["available_at"]}
            temporal=TemporalMetadata(available,available,available_at=available,available_at_basis=AvailabilityBasis.UPSTREAM_METADATA,valid_from=available)
            return NormalizedRecord(cik,"legal-entity",canonical_json_bytes(norm),(IdentityAttribute("cik",cik),),temporal,PUBLIC(SEC_MANIFEST.license_id),"sec-company/1",record.upstream_version)
        if kind!="filing":raise ValueError("sec_unknown_record_type")
        cik=str(d.get("cik",""));accn=str(d.get("accessionNumber",""))
        if len(cik)!=10 or not cik.isdigit() or len(accn)!=20 or accn.count("-")!=2:raise ValueError("sec_invalid_filing_identity")
        accepted=_dt(d.get("acceptanceDateTime"));filed=_dt(d.get("filed"))
        if accepted is None or filed is None:raise ValueError("sec_filing_timestamps_required")
        facts=[]
        for i,f in enumerate(d.get("facts",())):
            unit=str(f.get("unit",""))
            if unit not in KNOWN_UNITS:raise ValueError("sec_unknown_fact_unit")
            facts.append(dict(f,source_coordinate=f"{accn}:{f.get('context_id')}:{f.get('namespace')}:{f.get('tag')}:{i}"))
        sections=[]
        for i,s in enumerate((d.get("document") or {}).get("sections",())):
            if not str(s.get("id","")).strip() or not str(s.get("text","")).strip():raise ValueError("sec_document_section_invalid")
            sections.append(dict(s,source_coordinate=f"{accn}:{d['document']['name']}:{s['id']}"))
        norm={"kind":"sec-filing","id":accn,"accession":accn,"cik":cik,"company_name":d.get("company_name"),"form":d.get("form"),"filed_at":d.get("filed"),"accepted_at":d.get("acceptanceDateTime"),"amendment":bool(d.get("amendment")),"amends":d.get("amends"),"document_name":(d.get("document") or {}).get("name"),"sections":sections,"facts":facts}
        temporal=TemporalMetadata(filed,filed,published_at=filed,available_at=accepted,available_at_basis=AvailabilityBasis.UPSTREAM_METADATA,valid_from=filed)
        return NormalizedRecord(accn,"sec-filing",canonical_json_bytes(norm),(IdentityAttribute("accession",accn),IdentityAttribute("cik",cik)),temporal,PUBLIC(SEC_MANIFEST.license_id),"sec-filing-xbrl/1",record.upstream_version)

class FredAlfredNormalizer:
    normalizer_fingerprint="fred-alfred-normalizer/1"
    def normalize(self,record):
        d=json.loads(record.raw_bytes.decode());series=str(d.get("series_id",""));date=str(d.get("date",""));unit=str(d.get("units","")).lower()
        if not series or not date or unit not in KNOWN_UNITS:raise ValueError("fred_invalid_identity_or_unit")
        vintage=_dt(d["realtime_start"]);obs=_dt(date);value=None if d.get("value") in (None,".") else float(d["value"])
        norm={"kind":"macro-observation","id":f"{series}|{date}","series_id":series,"title":d.get("title"),"observation_date":date,"value":value,"unit":unit,"frequency":d.get("frequency"),"seasonal_adjustment":d.get("seasonal_adjustment"),"realtime_start":d["realtime_start"],"realtime_end":d.get("realtime_end"),"source_coordinate":f"{series}:{date}:{d['realtime_start']}","available_at":vintage.isoformat().replace("+00:00","Z")}
        temporal=TemporalMetadata(vintage,vintage,published_at=None,available_at=vintage,available_at_basis=AvailabilityBasis.UPSTREAM_METADATA,valid_from=obs)
        return NormalizedRecord(f"{series}|{date}","macro-observation",canonical_json_bytes(norm),(IdentityAttribute("series_id",series),IdentityAttribute("observation_date",date)),temporal,PUBLIC(FRED_MANIFEST.license_id),"fred-alfred-observation/1",record.upstream_version)

class PriceNormalizer:
    normalizer_fingerprint="licensed-price-normalizer/1"
    def normalize(self,record):
        d=json.loads(record.raw_bytes.decode());currency=str(d.get("currency",""))
        if currency!="USD":raise ValueError("price_unknown_or_unsupported_currency")
        close=float(d["close"])
        if close<=0:raise ValueError("price_must_be_positive")
        available=_dt(d["available_at"]);date=_dt(d["trading_date"]);adjusted=str(d.get("adjusted","")).lower()=="true"
        norm={"kind":"market-price","id":f"{d['security_id']}|{d['trading_date']}|{d['provider']}","security_id":d["security_id"],"ticker":d["ticker"],"exchange":d["exchange"],"trading_date":d["trading_date"],"close":close,"currency":currency,"calendar":d["calendar"],"timezone":d["timezone"],"adjusted":adjusted,"provider":d["provider"],"corporate_action_version":d.get("corporate_action_version"),"available_at":d["available_at"],"source_coordinate":record.record_key}
        temporal=TemporalMetadata(available,available,available_at=available,available_at_basis=AvailabilityBasis.UPSTREAM_METADATA,valid_from=date)
        return NormalizedRecord(norm["id"],"market-price",canonical_json_bytes(norm),(IdentityAttribute("security_id",d["security_id"]),IdentityAttribute("trading_date",d["trading_date"]),IdentityAttribute("provider",d["provider"])),temporal,PUBLIC(PRICE_MANIFEST.license_id),"market-price/1",record.upstream_version)

class CorporateActionNormalizer:
    normalizer_fingerprint="corporate-action-normalizer/1"
    def normalize(self,record):
        d=json.loads(record.raw_bytes.decode());available=_dt(d["available_at"]);effective=_dt(d["effective_date"]);ratio=float(d["ratio"])
        if d.get("currency")!="USD" or ratio<=0:raise ValueError("corporate_action_invalid_unit_or_ratio")
        stable=f"{d['security_id']}|{d['action_type']}|{d['effective_date']}|{d['provider']}"
        norm={"kind":"corporate-action","id":stable,"security_id":d["security_id"],"action_type":d["action_type"],"effective_date":d["effective_date"],"ratio":ratio,"currency":d["currency"],"provider":d["provider"],"available_at":d["available_at"],"source_coordinate":record.record_key}
        temporal=TemporalMetadata(available,available,available_at=available,available_at_basis=AvailabilityBasis.UPSTREAM_METADATA,valid_from=effective)
        return NormalizedRecord(stable,"corporate-action",canonical_json_bytes(norm),(IdentityAttribute("security_id",d["security_id"]),),temporal,PUBLIC(ACTION_MANIFEST.license_id),"corporate-action/1",record.upstream_version)

class SecurityMasterNormalizer:
    normalizer_fingerprint="security-master-normalizer/1"
    def normalize(self,record):
        d=json.loads(record.raw_bytes.decode());available=_dt(d["available_at"]);start=_dt(d["alias_from"]);end=_dt(d.get("alias_to"))
        if not all(str(d.get(k,"")).strip() for k in ("security_id","issuer_cik","ticker","exchange")):raise ValueError("security_master_identity_required")
        norm={"kind":"security-master","id":d["id"],**d}
        temporal=TemporalMetadata(available,available,available_at=available,available_at_basis=AvailabilityBasis.UPSTREAM_METADATA,valid_from=start,valid_to=end)
        return NormalizedRecord(d["id"],"security-alias",canonical_json_bytes(norm),(IdentityAttribute("security_id",d["security_id"]),IdentityAttribute("ticker",d["ticker"]),IdentityAttribute("exchange",d["exchange"])),temporal,PUBLIC(SECURITY_MASTER_MANIFEST.license_id),"security-master/1",record.upstream_version)
