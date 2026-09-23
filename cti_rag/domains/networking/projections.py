from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime,timezone
from cti_rag.contracts import AccessLabel,AssertionQualifier,CanonicalPassageLocator,ComponentFingerprint,EpistemicKind,EpistemicMetadata,Passage,PolicyLabels,ProcessingClass,ProvenanceRef,SourceAssertion,JsonPointerLocator,locator_to_data
from cti_rag.graph import CanonicalEntity
from cti_rag.retrieval import ExactRecord,LexicalDocument,normalize_search_text
from .sources import RFC_MANIFEST,BGP_MANIFEST,RPKI_MANIFEST,DNS_MANIFEST,RDAP_MANIFEST
UTC=timezone.utc
def _dt(v):
    if not v:return None
    return datetime.fromisoformat(str(v).replace("Z","+00:00")).astimezone(UTC)
def _policy(source_id):
    license_id={RFC_MANIFEST.source_id:RFC_MANIFEST.license_id,BGP_MANIFEST.source_id:BGP_MANIFEST.license_id,RPKI_MANIFEST.source_id:RPKI_MANIFEST.license_id,DNS_MANIFEST.source_id:DNS_MANIFEST.license_id,RDAP_MANIFEST.source_id:RDAP_MANIFEST.license_id}.get(source_id)
    return PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,license_id=license_id,retention_class="standard")
@dataclass(frozen=True)
class NetworkingProjectionBundle:
    exact:tuple=();lexical:tuple=();entities:tuple=();assertions:tuple=();structured_rows:tuple=()

class NetworkingProjectionProjector:
    def project_one(self,*,normalized_bytes,artifact_uid,revision_uid,object_uid,source_id,system_manifest_id="fixture"):
        d=json.loads(normalized_bytes.decode());kind=d["kind"];policy=_policy(source_id);exact=[];lex=[];entities=[];assertions=[];rows=[]
        available=_dt(d.get("available_at") or d.get("published_at"));vf=_dt(d.get("valid_from") or d.get("observed_at"));vt=_dt(d.get("valid_to") or d.get("observed_until"))
        if kind=="rfc":
            rid=d["id"];loc=CanonicalPassageLocator("rfc-document",rid)
            exact.append(ExactRecord(revision_uid,object_uid,"rfc","rfc",rid,"networking",source_id,"public",AccessLabel.PUBLIC,available or _dt(d["published_at"]),vf,json.dumps(None) if False else None,json.dumps(locator_to_data(loc),sort_keys=True,separators=(",",":")),rid))
            rfc=CanonicalEntity("rfc","rfc",rid,rid,policy,source_id,available or _dt(d["published_at"]),vf,vt,system_manifest_id);entities.append(rfc)
            chunker=ComponentFingerprint("rfc-section","1")
            for sec in d["sections"]:
                locator=CanonicalPassageLocator("rfc-section",f"{rid}#{sec['number']}")
                passage=Passage(artifact_uid,revision_uid,locator,sec["text"],chunker,EpistemicMetadata(EpistemicKind.SOURCE_CLAIM))
                lex.append(LexicalDocument(passage.passage_uid,revision_uid,object_uid,"rfc","rfc",rid,"networking",source_id,"public",AccessLabel.PUBLIC,available or _dt(d["published_at"]),vf,vt,json.dumps(locator_to_data(locator),sort_keys=True,separators=(",",":")),sec["text"],normalize_search_text(sec["text"]),normalize_search_text(f"{rid} {d['title']} section {sec['number']} {sec['title']}"),"unicode61/1"))
            for pred,key in (("updates","updates"),("obsoletes","obsoletes")):
                for i,target in enumerate(d.get(key,())):
                    other=CanonicalEntity("rfc","rfc",target,target,policy,source_id,available or _dt(d["published_at"]),None,None,system_manifest_id);entities.append(other)
                    assertions.append(SourceAssertion(revision_uid,rfc.ref,pred,other.ref,(AssertionQualifier("rfc_metadata",key),),(ProvenanceRef(revision_uid,JsonPointerLocator(f"/{key}/{i}")),),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=policy,available_at=available or _dt(d["published_at"]),valid_from=vf,system_manifest_id=system_manifest_id))
        elif kind=="bgp-observation":
            prefix=CanonicalEntity("cidr","prefix",d["prefix"],d["prefix"],policy,source_id,available,vf,vt,system_manifest_id);asn=CanonicalEntity("asn","asn",d["origin_asn"],d["origin_asn"],policy,source_id,available,vf,vt,system_manifest_id);entities.extend((prefix,asn))
            assertions.append(SourceAssertion(revision_uid,prefix.ref,"announced_by",asn.ref,(AssertionQualifier("collector",d["collector"]),AssertionQualifier("vantage_point",d["vantage_point"])),(ProvenanceRef(revision_uid,JsonPointerLocator("/origin_asn")),),EpistemicMetadata(EpistemicKind.OBSERVATION),source_id=source_id,policy=policy,available_at=available,valid_from=vf,valid_to=vt,system_manifest_id=system_manifest_id))
            rows.append(("network_bgp",_common(d,revision_uid,source_id,system_manifest_id)|{"prefix":d["prefix"],"prefix_start":d["prefix_start"],"prefix_end":d["prefix_end"],"prefix_family":d["prefix_family"],"prefix_length":d["prefix_length"],"collector":d["collector"],"vantage_point":d["vantage_point"],"peer_asn":d["peer_asn"],"origin_asn":d["origin_asn"],"observation_start":d["observed_at"],"observation_end":d.get("observed_until"),"as_path":" ".join(d.get("as_path",()))}))
        elif kind=="rpki-authorization":
            prefix=CanonicalEntity("cidr","prefix",d["prefix"],d["prefix"],policy,source_id,available,vf,vt,system_manifest_id);asn=CanonicalEntity("asn","asn",d["asn"],d["asn"],policy,source_id,available,vf,vt,system_manifest_id);entities.extend((prefix,asn))
            assertions.append(SourceAssertion(revision_uid,prefix.ref,"authorized_origin",asn.ref,(AssertionQualifier("max_length",str(d["max_length"])),),(ProvenanceRef(revision_uid,JsonPointerLocator("/asn")),),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=policy,available_at=available,valid_from=vf,valid_to=vt,system_manifest_id=system_manifest_id))
            rows.append(("network_rpki",_common(d,revision_uid,source_id,system_manifest_id)|{"prefix":d["prefix"],"prefix_start":d["prefix_start"],"prefix_end":d["prefix_end"],"prefix_family":d["prefix_family"],"prefix_length":d["prefix_length"],"max_length":d["max_length"],"asn":d["asn"]}))
        elif kind=="dns-observation":
            rows.append(("network_dns",_common(d,revision_uid,source_id,system_manifest_id)|{"qname":d["qname"],"rrtype":d["rrtype"],"rdata":d["rdata"],"ttl_seconds":d["ttl"],"resolver":d["resolver"],"vantage_point":d["vantage_point"],"observed_at":d["observed_at"]}))
        elif kind=="rdap-registration":
            prefix=CanonicalEntity("cidr","prefix",d["resource"],d["resource"],policy,source_id,available,vf,vt,system_manifest_id);org=CanonicalEntity("rdap","legal-entity",d["entity_handle"],d.get("entity_name") or d["entity_handle"],policy,source_id,available,vf,vt,system_manifest_id);entities.extend((prefix,org))
            assertions.append(SourceAssertion(revision_uid,prefix.ref,"registered_to",org.ref,(AssertionQualifier("registration_semantics","rdap-registration"),),(ProvenanceRef(revision_uid,JsonPointerLocator("/entity_handle")),),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=policy,available_at=available,valid_from=vf,valid_to=vt,system_manifest_id=system_manifest_id))
            rows.append(("network_rdap",_common(d,revision_uid,source_id,system_manifest_id)|{"prefix":d["resource"],"prefix_start":d["prefix_start"],"prefix_end":d["prefix_end"],"prefix_family":d["prefix_family"],"prefix_length":d["prefix_length"],"entity_handle":d["entity_handle"],"entity_name":d.get("entity_name"),"registration_start":d.get("registration_start"),"registration_end":d.get("registration_end")}))
        return NetworkingProjectionBundle(tuple(exact),tuple(lex),tuple(entities),tuple(assertions),tuple(rows))

def _common(d,revision_uid,source_id,manifest):
    available=d.get("available_at") or d.get("published_at");vf=d.get("valid_from") or d.get("observed_at");vt=d.get("valid_to") or d.get("observed_until")
    return {"revision_uid":revision_uid,"revision_order":int((_dt(available) or datetime(1970,1,1,tzinfo=UTC)).timestamp()),"available_at":available,"valid_from":vf,"valid_to":vt,"system_manifest_id":manifest,"dependency_available_at_max":None,"dependency_manifest_id":None,"tenant_id":"public","domain":"networking","source_id":source_id,"access_label":"public"}

class NetworkingProjectionRebuilder:
    def __init__(self,metadata_store,object_store,projector=None):self.meta=metadata_store;self.objects=object_store;self.projector=projector or NetworkingProjectionProjector()
    def rebuild(self,source_ids=("rfc-editor","ripe-ris-fixture","rpki-roa-fixture","dns-observation-fixture","rdap-registration-fixture"),system_manifest_id="network-fixture"):
        refs={r.digest:r for r in self.objects.iter_refs()};out=NetworkingProjectionBundle()
        exact=[];lex=[];entities=[];assertions=[];rows=[]
        for artifact_uid,revision_uid,digest,retention,object_uid,source_id,stable_id,object_type,revoked in self.meta.projection_artifacts(source_ids):
            if revoked or digest not in refs:continue
            bundle=self.projector.project_one(normalized_bytes=self.objects.get(refs[digest]),artifact_uid=artifact_uid,revision_uid=revision_uid,object_uid=object_uid,source_id=source_id,system_manifest_id=system_manifest_id)
            exact.extend(bundle.exact);lex.extend(bundle.lexical);entities.extend(bundle.entities);assertions.extend(bundle.assertions);rows.extend(bundle.structured_rows)
        return NetworkingProjectionBundle(tuple(exact),tuple(lex),tuple(sorted({e.entity_uid:e for e in entities}.values(),key=lambda e:e.entity_uid)),tuple(assertions),tuple(rows))
