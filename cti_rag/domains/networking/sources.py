from __future__ import annotations
import json,xml.etree.ElementTree as ET
from datetime import datetime,timezone,timedelta
from ipaddress import ip_address,ip_network
from cti_rag.contracts import AccessLabel,AvailabilityBasis,IdentityAttribute,PolicyLabels,ProcessingClass,TemporalMetadata,canonical_json_bytes
from cti_rag.ingestion import SourceManifest
from cti_rag.ports import BackendCapabilities,NormalizedRecord,SourcePage,SourceRecord
from .fixtures import RFC_1771_XML,RFC_4271_XML,BGP_FIXTURE,RPKI_FIXTURE,DNS_FIXTURE,RDAP_FIXTURE

UTC=timezone.utc
def _dt(value):
    if value is None:return None
    return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(UTC)
def _range(prefix):
    net=ip_network(prefix,strict=True)
    return net.network_address.packed.hex().rjust(32,"0"),net.broadcast_address.packed.hex().rjust(32,"0"),net.version,net.prefixlen
PUBLIC=lambda license_id:PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,license_id=license_id,retention_class="standard")

RFC_MANIFEST=SourceManifest("rfc-editor","networking","rfc-xml-document","rfc","rfc-number+content-digest","RFC-Editor-Publication",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","document revision","explicit RFC metadata relationship/update",AvailabilityBasis.SOURCE_PUBLISHED,
 ("exact","lexical","dense","graph"),source_uri="https://www.rfc-editor.org/",license_notice="RFC publication/copyright notices remain attached to source documents.",connector_fingerprint="rfc-document-connector/1",parser_fingerprint="rfc-document-normalizer/1")
BGP_MANIFEST=SourceManifest("ripe-ris-fixture","networking","bgp-observation-json","bgp-observation","collector+observation+content","RIPE-RIS-Terms",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","append observations/corrections","source correction tombstone if supplied",AvailabilityBasis.UPSTREAM_METADATA,
 ("structured","graph"),source_uri="https://ris.ripe.net/",license_notice="Fixture follows RIS-style BGP observation semantics; no live feed access claimed.",connector_fingerprint="bgp-observation-connector/1",parser_fingerprint="bgp-observation-normalizer/1")
RPKI_MANIFEST=SourceManifest("rpki-roa-fixture","networking","rpki-authorization-json","rpki-authorization","roa identity+serial","RPKI-Repository-Terms",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","snapshot serial","withdrawal/replacement",AvailabilityBasis.UPSTREAM_METADATA,
 ("structured","graph"),source_uri="https://rpki-validator.ripe.net/",license_notice="Offline ROA-format fixture only; live validator/repository lifecycle not claimed.",connector_fingerprint="rpki-connector/1",parser_fingerprint="rpki-normalizer/1")
DNS_MANIFEST=SourceManifest("dns-observation-fixture","networking","dns-observation-json","dns-observation","resolver+time+answer","fixture",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","append observations","observation expiry/explicit deletion",AvailabilityBasis.FIRST_OBSERVED,
 ("structured",),source_uri="fixture:network-dns",license_notice="Synthetic DNS observations; answer records are observations, not ownership claims.",connector_fingerprint="dns-observation-connector/1",parser_fingerprint="dns-observation-normalizer/1")
RDAP_MANIFEST=SourceManifest("rdap-registration-fixture","networking","rdap-registration-json","rdap-registration","resource+entity+observation","fixture",
 AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,"standard","append source observations","explicit source correction/removal",AvailabilityBasis.FIRST_OBSERVED,
 ("structured","graph"),source_uri="fixture:network-rdap",license_notice="Synthetic RDAP-like fixture; registration is distinct from route origin and RPKI authorization.",connector_fingerprint="rdap-connector/1",parser_fingerprint="rdap-normalizer/1")

class TupleConnector:
    capabilities=BackendCapabilities(pagination=True,cancellation=True,max_batch_size=1000)
    def __init__(self,source_id,rows,page_size=1000):self.source_id=source_id;self.rows=tuple(rows);self.page_size=page_size;self.connector_fingerprint=f"{source_id}-connector/1"
    async def fetch_page(self,cursor=None,deadline=None,cancellation_token=None):
        start=int(cursor or 0);end=min(len(self.rows),start+self.page_size);records=[]
        for row in self.rows:
            raw=row if isinstance(row,bytes) else canonical_json_bytes(row)
            if isinstance(row,bytes):
                try:root=ET.fromstring(row);key=f"RFC {root.attrib['number']}";version=root.attrib.get("published","unknown")
                except Exception:key="invalid-rfc";version="invalid"
            else:key=str(row.get("id","missing"));version=str(row.get("version","unknown"))
            records.append(SourceRecord(key,raw,version))
        return SourcePage(tuple(records[start:end]),None if end>=len(records) else str(end),end>=len(records))

def RfcConnector(rows=(RFC_1771_XML,RFC_4271_XML)):return TupleConnector(RFC_MANIFEST.source_id,rows)
def BgpConnector(rows=BGP_FIXTURE):return TupleConnector(BGP_MANIFEST.source_id,rows)
def RpkiConnector(rows=RPKI_FIXTURE):return TupleConnector(RPKI_MANIFEST.source_id,rows)
def DnsConnector(rows=DNS_FIXTURE):return TupleConnector(DNS_MANIFEST.source_id,rows)
def RdapConnector(rows=RDAP_FIXTURE):return TupleConnector(RDAP_MANIFEST.source_id,rows)

class RfcNormalizer:
    normalizer_fingerprint="rfc-document-normalizer/1"
    def normalize(self,record):
        try:root=ET.fromstring(record.raw_bytes)
        except Exception as exc:raise ValueError("invalid_rfc_xml") from exc
        number=str(root.attrib.get("number","")).strip()
        if not number.isdigit():raise ValueError("rfc_number_required")
        rid=f"RFC {int(number)}";published=_dt(root.attrib.get("published"))
        if published is None:raise ValueError("rfc_published_timestamp_required")
        title=(root.findtext("title") or "").strip()
        sections=[]
        for node in root.findall("section"):
            sec=str(node.attrib.get("number","")).strip();text=" ".join("".join(node.itertext()).split())
            if not sec or not text:raise ValueError("rfc_section_requires_number_and_text")
            sections.append({"number":sec,"title":str(node.attrib.get("title","")).strip(),"text":text})
        if not sections:raise ValueError("rfc_sections_required")
        def refs(name):return [f"RFC {int(v)}" for v in root.attrib.get(name,"").split(",") if v.strip().isdigit()]
        normalized={"kind":"rfc","id":rid,"number":int(number),"title":title,"published_at":published.isoformat().replace("+00:00","Z"),
                    "updates":refs("updates"),"updated_by":refs("updated-by"),"obsoletes":refs("obsoletes"),"obsoleted_by":refs("obsoleted-by"),"sections":sections}
        temporal=TemporalMetadata(published,published,published_at=published,available_at=published,available_at_basis=AvailabilityBasis.SOURCE_PUBLISHED,valid_from=published)
        return NormalizedRecord(rid,"rfc",canonical_json_bytes(normalized),(IdentityAttribute("rfc_id",rid),),temporal,PUBLIC(RFC_MANIFEST.license_id),"rfc-document/1",record.upstream_version)

class JsonNetworkNormalizer:
    kind="";object_type="";manifest=None;normalizer_fingerprint=""
    def validate(self,data):return data
    def normalize(self,record):
        try:data=json.loads(record.raw_bytes.decode())
        except Exception as exc:raise ValueError(f"invalid_{self.kind}_json") from exc
        data=self.validate(data);stable=str(data["id"]);available=_dt(data["available_at"])
        valid_from=_dt(data.get("valid_from") or data.get("observed_at"));valid_to=_dt(data.get("valid_to") or data.get("observed_until"))
        temporal=TemporalMetadata(valid_from or available,valid_from or available,published_at=None,available_at=available,available_at_basis=self.manifest.availability_basis,valid_from=valid_from,valid_to=valid_to)
        identity=(IdentityAttribute("source_record_id",stable),)
        return NormalizedRecord(stable,self.object_type,canonical_json_bytes({"kind":self.kind,**data}),identity,temporal,PUBLIC(self.manifest.license_id),f"{self.kind}/1",record.upstream_version)

class BgpNormalizer(JsonNetworkNormalizer):
    kind="bgp-observation";object_type="bgp-observation";manifest=BGP_MANIFEST;normalizer_fingerprint="bgp-observation-normalizer/1"
    def validate(self,data):
        start,end,family,length=_range(data["prefix"]);data=dict(data,prefix=str(ip_network(data["prefix"],strict=True)),prefix_start=start,prefix_end=end,prefix_family=family,prefix_length=length)
        for key in ("collector","vantage_point","peer_asn","origin_asn","observed_at","available_at"):
            if not str(data.get(key,"")).strip():raise ValueError(f"bgp_missing_{key}")
        return data
class RpkiNormalizer(JsonNetworkNormalizer):
    kind="rpki-authorization";object_type="rpki-authorization";manifest=RPKI_MANIFEST;normalizer_fingerprint="rpki-normalizer/1"
    def validate(self,data):
        start,end,family,length=_range(data["prefix"]);ml=int(data["max_length"])
        if ml<length or ml>(32 if family==4 else 128):raise ValueError("rpki_invalid_max_length")
        return dict(data,prefix=str(ip_network(data["prefix"],strict=True)),prefix_start=start,prefix_end=end,prefix_family=family,prefix_length=length,max_length=ml)
class DnsNormalizer(JsonNetworkNormalizer):
    kind="dns-observation";object_type="dns-observation";manifest=DNS_MANIFEST;normalizer_fingerprint="dns-observation-normalizer/1"
    def validate(self,data):
        ttl=int(data["ttl"])
        if ttl<0:raise ValueError("dns_negative_ttl")
        typ=str(data["rrtype"]).upper()
        if typ in ("A","AAAA"):
            addr=ip_address(str(data["rdata"]))
            if (typ=="A" and addr.version!=4) or (typ=="AAAA" and addr.version!=6):raise ValueError("dns_rrtype_address_family_mismatch")
        observed=_dt(data["observed_at"]);return dict(data,rrtype=typ,ttl=ttl,valid_from=data["observed_at"],valid_to=(observed+timedelta(seconds=ttl)).isoformat().replace("+00:00","Z"))
class RdapNormalizer(JsonNetworkNormalizer):
    kind="rdap-registration";object_type="rdap-registration";manifest=RDAP_MANIFEST;normalizer_fingerprint="rdap-normalizer/1"
    def validate(self,data):
        resource=str(ip_network(data["resource"],strict=True));start,end,family,length=_range(resource)
        if not str(data.get("entity_handle","")).strip():raise ValueError("rdap_entity_handle_required")
        return dict(data,resource=resource,prefix=resource,prefix_start=start,prefix_end=end,prefix_family=family,prefix_length=length,valid_from=data.get("registration_start"),valid_to=data.get("registration_end"))
