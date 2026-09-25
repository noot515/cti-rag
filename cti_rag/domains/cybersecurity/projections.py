from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime,timezone
from cti_rag.contracts import (
    AccessLabel,AssertionQualifier,EntityRef,EpistemicKind,EpistemicMetadata,JsonPointerLocator,PolicyLabels,
    ProcessingClass,ProvenanceRef,SourceAssertion
)
from cti_rag.graph import CanonicalEntity
from cti_rag.ingestion import ObjectRef
from cti_rag.retrieval import StructuredJsonProjector

UTC=timezone.utc
def _dt(v):
    if not v:return None
    if len(v)==10:v=v+"T00:00:00Z"
    return datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(UTC)
def _policy(source_id):
    license_id={"cve-list-v5":"CVE-Terms-of-Use","cisa-kev":"CISA-Terms-of-Use","mitre-attack-stix":"MITRE-ATTACK-Terms"}.get(source_id)
    return PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,license_id=license_id,retention_class="standard")
@dataclass(frozen=True)
class CyberProjectionBundle:
    exact:tuple=(); lexical:tuple=(); entities:tuple=(); assertions:tuple=(); structured_rows:tuple=()

class CyberProjectionProjector:
    def __init__(self):self.text=StructuredJsonProjector()
    def project_one(self,*,normalized_bytes,artifact_uid,revision_uid,object_uid,source_id,system_manifest_id="fixture"):
        data=json.loads(normalized_bytes.decode());kind=data.get("kind");policy=_policy(source_id)
        exact=();lexical=();entities=[];assertions=[];rows=[]
        if kind=="cve":
            available=_dt(data.get("date_updated"));valid=_dt(data.get("date_published"))
            e,l=self.text.project(normalized_bytes=normalized_bytes,artifact_uid=artifact_uid,revision_uid=revision_uid,object_uid=object_uid,namespace="cve",object_type="cve",canonical_id=data["id"],domain="cybersecurity",source_id=source_id,tenant_id="public",access_label=AccessLabel.PUBLIC,available_at=available,valid_from=valid,text_pointers=("/summary",),context_prefix=data["id"])
            exact=(e,);lexical=l
            subject=CanonicalEntity("cve","cve",data["id"],data["id"],policy,source_id,available,valid,None,system_manifest_id)
            entities.append(subject)
            for i,cwe in enumerate(data.get("cwes",())):
                obj=CanonicalEntity("cwe","cwe",cwe,cwe,policy,source_id,available,valid,None,system_manifest_id);entities.append(obj)
                support=ProvenanceRef(revision_uid,JsonPointerLocator(f"/cwes/{i}"))
                assertions.append(SourceAssertion(revision_uid,subject.ref,"has_weakness",obj.ref,(AssertionQualifier("mapping_source","CVE problemTypes.cweId"),),(support,),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=policy,available_at=available,valid_from=valid,system_manifest_id=system_manifest_id))
            for metric in data.get("cvss",()):
                rows.append(("cyber_cvss",{
                    "revision_uid":revision_uid,"revision_order":int(available.timestamp()) if available else 0,"available_at":None if available is None else available.isoformat().replace("+00:00","Z"),
                    "valid_from":None if valid is None else valid.isoformat().replace("+00:00","Z"),"valid_to":None,"system_manifest_id":system_manifest_id,
                    "dependency_available_at_max":None,"dependency_manifest_id":None,"tenant_id":"public","domain":"cybersecurity","source_id":source_id,"access_label":"public",
                    "cve_id":data["id"],"cvss_scheme":metric.get("scheme"),"cvss_score":metric.get("base_score"),"cvss_severity":metric.get("severity"),"vector":metric.get("vector"),"source_container":metric.get("source_container")
                }))
        elif kind=="kev":
            available=_dt(data.get("date_added"))
            _e,l=self.text.project(normalized_bytes=normalized_bytes,artifact_uid=artifact_uid,revision_uid=revision_uid,object_uid=object_uid,namespace="kev",object_type="kev-entry",canonical_id=data["id"],domain="cybersecurity",source_id=source_id,tenant_id="public",access_label=AccessLabel.PUBLIC,available_at=available,valid_from=available,text_pointers=("/summary",),context_prefix=f"KEV {data['id']}")
            lexical=l
            rows.append(("cyber_kev",{
                "revision_uid":revision_uid,"revision_order":int(available.timestamp()) if available else 0,"available_at":None if available is None else available.isoformat().replace("+00:00","Z"),
                "valid_from":None if available is None else available.isoformat().replace("+00:00","Z"),"valid_to":None,"system_manifest_id":system_manifest_id,
                "dependency_available_at_max":None,"dependency_manifest_id":None,"tenant_id":"public","domain":"cybersecurity","source_id":source_id,"access_label":"public",
                "cve_id":data["id"],"kev":True,"date_added":data.get("date_added"),"due_date":data.get("due_date"),"known_ransomware_campaign_use":data.get("known_ransomware_campaign_use")
            }))
        elif kind=="attack-technique":
            available=_dt(data.get("modified"));valid=_dt(data.get("created"))
            e,l=self.text.project(normalized_bytes=normalized_bytes,artifact_uid=artifact_uid,revision_uid=revision_uid,object_uid=object_uid,namespace="attack",object_type="attack-technique",canonical_id=data["id"],domain="cybersecurity",source_id=source_id,tenant_id="public",access_label=AccessLabel.PUBLIC,available_at=available,valid_from=valid,text_pointers=("/description",),context_prefix=f"{data['id']} {data.get('name','')}")
            exact=(e,);lexical=l
            entities.append(CanonicalEntity("attack","attack-technique",data["id"],data.get("name") or data["id"],policy,source_id,available,valid,None,system_manifest_id))
        return CyberProjectionBundle(tuple(exact),tuple(lexical),tuple(entities),tuple(assertions),tuple(rows))

class CyberProjectionRebuilder:
    def __init__(self,metadata_store,object_store,projector=None):
        self.meta=metadata_store;self.objects=object_store;self.projector=projector or CyberProjectionProjector()
    def rebuild(self,source_ids=("cve-list-v5","cisa-kev","mitre-attack-stix"),system_manifest_id="fixture"):
        refs={r.digest:r for r in self.objects.iter_refs()}; exact=[];lexical=[];entities=[];assertions=[];rows=[];attack_docs=[];stix_to_entity={}
        for artifact_uid,revision_uid,digest,retention,object_uid,source_id,stable_id,object_type,revoked in self.meta.projection_artifacts(source_ids):
            if revoked:continue
            ref=refs.get(digest) or ObjectRef(digest,0,retention,"")
            if digest not in refs:continue
            raw=self.objects.get(ref); data=json.loads(raw.decode())
            bundle=self.projector.project_one(normalized_bytes=raw,artifact_uid=artifact_uid,revision_uid=revision_uid,object_uid=object_uid,source_id=source_id,system_manifest_id=system_manifest_id)
            exact.extend(bundle.exact);lexical.extend(bundle.lexical);entities.extend(bundle.entities);assertions.extend(bundle.assertions);rows.extend(bundle.structured_rows)
            if data.get("kind")=="attack-technique" and bundle.entities:stix_to_entity[data["stix_id"]]=bundle.entities[0]
            elif data.get("kind")=="attack-relationship":attack_docs.append((revision_uid,source_id,data))
        by_uid={e.entity_uid:e for e in entities}
        for revision_uid,source_id,data in attack_docs:
            left=stix_to_entity.get(data.get("source_ref"));right=stix_to_entity.get(data.get("target_ref"))
            if not left or not right:continue
            available=_dt(data.get("modified"));valid=_dt(data.get("created"));support=ProvenanceRef(revision_uid,JsonPointerLocator("/relationship_type"))
            assertions.append(SourceAssertion(revision_uid,left.ref,str(data["relationship_type"]),right.ref,(AssertionQualifier("mapping_source","ATT&CK STIX relationship"),),(support,),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=_policy(source_id),available_at=available,valid_from=valid,system_manifest_id=system_manifest_id))
        dedup_entities=tuple(sorted({e.entity_uid:e for e in entities}.values(),key=lambda e:e.entity_uid))
        return CyberProjectionBundle(tuple(exact),tuple(lexical),dedup_entities,tuple(assertions),tuple(rows))
