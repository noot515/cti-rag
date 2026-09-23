from __future__ import annotations
import json
from datetime import datetime,timezone
from cti_rag.contracts import AccessLabel,AvailabilityBasis,IdentityAttribute,PolicyLabels,ProcessingClass,TemporalMetadata,canonical_json_bytes
from cti_rag.ingestion import SourceManifest
from cti_rag.ports import BackendCapabilities,NormalizedRecord,SourceDeletion,SourcePage,SourceRecord
from .fixtures import ATTACK_STIX_FIXTURE,CVE_V5_FIXTURE,KEV_FIXTURE

UTC=timezone.utc
def _dt(value):
    if value is None:return None
    if len(value)==10:value=value+"T00:00:00Z"
    return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(UTC)
PUBLIC=lambda license_id:PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,license_id=license_id,retention_class="standard")

ATTACK_MANIFEST=SourceManifest(
    "mitre-attack-stix","cybersecurity","stix-2.1","attack-object","modified+content_digest","MITRE-ATTACK-Terms",
    AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","bundle/versioned objects","revoked/deprecated tombstone",AvailabilityBasis.UPSTREAM_METADATA,
    ("exact","lexical","dense","graph"),source_uri="https://attack.mitre.org/",license_notice="Reproduce MITRE copyright designation and ATT&CK license notice.",
    connector_fingerprint="attack-stix-connector/1",parser_fingerprint="attack-stix-normalizer/1")
CVE_MANIFEST=SourceManifest(
    "cve-list-v5","cybersecurity","cve-json-5","cve","dateUpdated+content_digest","CVE-Terms-of-Use",
    AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","git/release versioned record","explicit upstream tombstone/revocation",AvailabilityBasis.UPSTREAM_METADATA,
    ("exact","lexical","dense","graph","structured"),source_uri="https://github.com/CVEProject/cvelistV5",license_notice="CVE use subject to CVE Program Terms of Use and MITRE copyright designation.",
    connector_fingerprint="cve-list-v5-connector/1",parser_fingerprint="cve-json-v5-normalizer/1")
KEV_MANIFEST=SourceManifest(
    "cisa-kev","cybersecurity","cisa-kev-json","kev-entry","catalogVersion+content_digest","CISA-Terms-of-Use",
    AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","catalog version","entry removal tombstone",AvailabilityBasis.UPSTREAM_METADATA,
    ("lexical","dense","structured"),source_uri="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",license_notice="CISA source attribution/terms retained in manifest.",
    connector_fingerprint="cisa-kev-connector/1",parser_fingerprint="cisa-kev-normalizer/1")

class AttackStixConnector:
    source_id=ATTACK_MANIFEST.source_id;connector_fingerprint="attack-stix-connector/1"
    capabilities=BackendCapabilities(pagination=True,cancellation=True,max_batch_size=100)
    def __init__(self,bundle_bytes=ATTACK_STIX_FIXTURE,page_size=100):
        self.bundle_bytes=bundle_bytes;self.page_size=page_size
    def _records(self):
        try:data=json.loads(self.bundle_bytes.decode("utf-8"))
        except Exception:return (SourceRecord("invalid-stix",self.bundle_bytes,"invalid"),),()
        objects=data.get("objects")
        if data.get("type")!="bundle" or not isinstance(objects,list):return (SourceRecord("invalid-stix",self.bundle_bytes,"invalid"),),()
        records=[];deletions=[]
        for obj in objects:
            raw=canonical_json_bytes(obj);key=str(obj.get("id","missing-id"));version=str(obj.get("modified") or obj.get("x_mitre_version") or "unknown")
            records.append(SourceRecord(key,raw,version))
            if obj.get("revoked") is True or obj.get("x_mitre_deprecated") is True:
                external=next((r.get("external_id") for r in obj.get("external_references",()) if r.get("source_name")=="mitre-attack" and r.get("external_id")),None)
                deletions.append(SourceDeletion(str(external or key),"upstream ATT&CK revoked/deprecated"))
        return tuple(records),tuple(deletions)
    async def fetch_page(self,cursor=None,deadline=None,cancellation_token=None):
        records,deletions=self._records();start=int(cursor or 0);end=min(len(records),start+self.page_size);next_cursor=None if end>=len(records) else str(end)
        return SourcePage(records[start:end],next_cursor,end>=len(records),deletions if end>=len(records) else ())

class AttackStixNormalizer:
    normalizer_fingerprint="attack-stix-normalizer/1"
    def normalize(self,record):
        try:data=json.loads(record.raw_bytes.decode("utf-8"))
        except Exception as exc:raise ValueError("invalid_stix_json") from exc
        if data.get("spec_version")!="2.1" or not str(data.get("id","")).count("--")==1:raise ValueError("invalid_stix_2_1_object")
        typ=data.get("type")
        if typ=="attack-pattern":
            ext=next((r.get("external_id") for r in data.get("external_references",()) if r.get("source_name")=="mitre-attack" and r.get("external_id")),None)
            if not ext or not str(ext).startswith("T"):raise ValueError("attack_pattern_missing_mitre_external_id")
            stable=str(ext).upper();obj_type="attack-technique";identity=(IdentityAttribute("attack_id",stable),IdentityAttribute("stix_id",data["id"]))
            normalized={"kind":"attack-technique","id":stable,"stix_id":data["id"],"name":str(data.get("name","")).strip(),"description":str(data.get("description","")).strip(),"version":str(data.get("x_mitre_version","")),"created":data.get("created"),"modified":data.get("modified"),"revoked":bool(data.get("revoked",False)),"deprecated":bool(data.get("x_mitre_deprecated",False))}
        elif typ=="relationship":
            for k in ("source_ref","target_ref","relationship_type"):
                if not str(data.get(k,"")).strip():raise ValueError("attack_relationship_missing_field")
            stable=str(data["id"]);obj_type="attack-relationship";identity=(IdentityAttribute("stix_id",stable),)
            normalized={"kind":"attack-relationship","id":stable,"source_ref":data["source_ref"],"target_ref":data["target_ref"],"relationship_type":data["relationship_type"],"description":str(data.get("description","")).strip(),"created":data.get("created"),"modified":data.get("modified"),"revoked":bool(data.get("revoked",False))}
        else:raise ValueError("unsupported_attack_stix_type")
        modified=_dt(data.get("modified"));created=_dt(data.get("created")) or modified
        if modified is None:raise ValueError("attack_object_missing_modified")
        temporal=TemporalMetadata(created,created,published_at=created,available_at=modified,available_at_basis=AvailabilityBasis.UPSTREAM_METADATA,valid_from=created)
        return NormalizedRecord(stable,obj_type,canonical_json_bytes(normalized),identity,temporal,PUBLIC(ATTACK_MANIFEST.license_id),f"attack-stix-{typ}/1",record.upstream_version)

class CveListConnector:
    source_id=CVE_MANIFEST.source_id;connector_fingerprint="cve-list-v5-connector/1";capabilities=BackendCapabilities(pagination=True,cancellation=True,max_batch_size=100)
    def __init__(self,records=(CVE_V5_FIXTURE,),deletions=(),page_size=100):self.records=tuple(records);self.deletions=tuple(deletions);self.page_size=page_size
    async def fetch_page(self,cursor=None,deadline=None,cancellation_token=None):
        start=int(cursor or 0);end=min(len(self.records),start+self.page_size);out=[]
        for raw in self.records:
            try:d=json.loads(raw.decode());key=str(d.get("cveMetadata",{}).get("cveId","invalid-cve"));ver=str(d.get("cveMetadata",{}).get("dateUpdated") or "unknown")
            except Exception:key="invalid-cve";ver="invalid"
            out.append(SourceRecord(key,raw,ver))
        next_cursor=None if end>=len(out) else str(end);return SourcePage(tuple(out[start:end]),next_cursor,end>=len(out),self.deletions if end>=len(out) else ())

class CveJsonV5Normalizer:
    normalizer_fingerprint="cve-json-v5-normalizer/1"
    def normalize(self,record):
        try:data=json.loads(record.raw_bytes.decode("utf-8"))
        except Exception as exc:raise ValueError("invalid_cve_json") from exc
        if data.get("dataType")!="CVE_RECORD" or not str(data.get("dataVersion","")).startswith("5."):raise ValueError("unsupported_cve_record_format")
        meta=data.get("cveMetadata") or {};cve=str(meta.get("cveId","")).upper()
        if not cve.startswith("CVE-") or meta.get("state") not in ("PUBLISHED","REJECTED"):raise ValueError("invalid_cve_metadata")
        published=_dt(meta.get("datePublished"));updated=_dt(meta.get("dateUpdated") or meta.get("datePublished"))
        if updated is None:raise ValueError("cve_missing_update_time")
        descriptions=[];cwes=[];metrics=[]
        containers=data.get("containers") or {}
        for container_name,container in containers.items():
            values=container if isinstance(container,list) else (container,)
            for body in values:
                for item in body.get("descriptions",()):descriptions.append({"lang":item.get("lang"),"value":item.get("value")})
                for group in body.get("problemTypes",()):
                    for item in group.get("descriptions",()):
                        cwe=item.get("cweId")
                        if item.get("type")=="CWE" and not cwe:raise ValueError("cve_cwe_mapping_missing_cweId")
                        if cwe:
                            cwe=str(cwe).upper()
                            if not cwe.startswith("CWE-") or not cwe[4:].isdigit():raise ValueError("cve_invalid_cwe_mapping")
                            cwes.append(cwe)
                for metric_group in body.get("metrics",()):
                    for key,value in metric_group.items():
                        if not key.lower().startswith("cvss") or not isinstance(value,dict):continue
                        version=str(value.get("version") or key.replace("cvssV","").replace("_","."))
                        metrics.append({"scheme":f"CVSS:{version}","base_score":value.get("baseScore"),"severity":value.get("baseSeverity"),"vector":value.get("vectorString"),"source_container":container_name})
        summary=next((str(x["value"]) for x in descriptions if x.get("lang")=="en" and x.get("value")),next((str(x["value"]) for x in descriptions if x.get("value")),""))
        normalized={"kind":"cve","id":cve,"state":meta["state"],"summary":summary,"descriptions":descriptions,"cwes":sorted(set(cwes)),"cvss":metrics,"date_published":None if published is None else published.isoformat().replace("+00:00","Z"),"date_updated":updated.isoformat().replace("+00:00","Z")}
        temporal=TemporalMetadata(published or updated,published or updated,published_at=published,available_at=updated,available_at_basis=AvailabilityBasis.UPSTREAM_METADATA,valid_from=published)
        return NormalizedRecord(cve,"cve",canonical_json_bytes(normalized),(IdentityAttribute("cve_id",cve),),temporal,PUBLIC(CVE_MANIFEST.license_id),"cve-json-5/1",record.upstream_version)

class KevConnector:
    source_id=KEV_MANIFEST.source_id;connector_fingerprint="cisa-kev-connector/1";capabilities=BackendCapabilities(pagination=True,cancellation=True,max_batch_size=1000)
    def __init__(self,catalog_bytes=KEV_FIXTURE,page_size=1000,previous_cve_ids=()):self.catalog_bytes=catalog_bytes;self.page_size=page_size;self.previous_cve_ids=tuple(previous_cve_ids)
    def _records(self):
        try:data=json.loads(self.catalog_bytes.decode("utf-8"))
        except Exception:return (SourceRecord("invalid-kev",self.catalog_bytes,"invalid"),)
        version=str(data.get("catalogVersion") or data.get("dateReleased") or "unknown");records=[]
        for item in data.get("vulnerabilities",()):
            body=dict(item);body["_catalogVersion"]=version;body["_dateReleased"]=data.get("dateReleased");raw=canonical_json_bytes(body);records.append(SourceRecord(str(item.get("cveID","invalid")),raw,version))
        return tuple(records)
    async def fetch_page(self,cursor=None,deadline=None,cancellation_token=None):
        rows=self._records();start=int(cursor or 0);end=min(len(rows),start+self.page_size);next_cursor=None if end>=len(rows) else str(end)
        current=tuple(r.record_key for r in rows);deletions=tuple(SourceDeletion(cve,"removed from later KEV catalog") for cve in self.previous_cve_ids if cve not in current) if end>=len(rows) else ()
        return SourcePage(rows[start:end],next_cursor,end>=len(rows),deletions)

class KevNormalizer:
    normalizer_fingerprint="cisa-kev-normalizer/1"
    def normalize(self,record):
        try:data=json.loads(record.raw_bytes.decode("utf-8"))
        except Exception as exc:raise ValueError("invalid_kev_json") from exc
        cve=str(data.get("cveID","")).upper();date_added=_dt(data.get("dateAdded"))
        if not cve.startswith("CVE-") or date_added is None:raise ValueError("invalid_kev_entry")
        normalized={"kind":"kev","id":cve,"vendor_project":data.get("vendorProject"),"product":data.get("product"),"name":data.get("vulnerabilityName"),"summary":data.get("shortDescription"),"date_added":data.get("dateAdded"),"due_date":data.get("dueDate"),"known_ransomware_campaign_use":data.get("knownRansomwareCampaignUse"),"required_action":data.get("requiredAction"),"notes":data.get("notes"),"catalog_version":data.get("_catalogVersion")}
        temporal=TemporalMetadata(date_added,date_added,published_at=date_added,available_at=date_added,available_at_basis=AvailabilityBasis.UPSTREAM_METADATA,valid_from=date_added)
        return NormalizedRecord(cve,"kev-entry",canonical_json_bytes(normalized),(IdentityAttribute("cve_id",cve),),temporal,PUBLIC(KEV_MANIFEST.license_id),"cisa-kev/1",record.upstream_version)
