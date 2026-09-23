from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime,timezone
from cti_rag.contracts import AccessLabel,AssertionQualifier,CanonicalPassageLocator,ComponentFingerprint,EpistemicKind,EpistemicMetadata,Passage,PolicyLabels,ProcessingClass,ProvenanceRef,SourceAssertion,JsonPointerLocator,locator_to_data
from cti_rag.graph import CanonicalEntity
from cti_rag.retrieval import ExactRecord,LexicalDocument,normalize_search_text
from .sources import SEC_MANIFEST,FRED_MANIFEST,PRICE_MANIFEST,ACTION_MANIFEST,SECURITY_MASTER_MANIFEST
UTC=timezone.utc
def _dt(v):
    if not v:return None
    if len(str(v))==10:v=str(v)+"T00:00:00Z"
    return datetime.fromisoformat(str(v).replace("Z","+00:00")).astimezone(UTC)
def _policy(source_id):
    license_id={SEC_MANIFEST.source_id:SEC_MANIFEST.license_id,FRED_MANIFEST.source_id:FRED_MANIFEST.license_id,PRICE_MANIFEST.source_id:PRICE_MANIFEST.license_id,ACTION_MANIFEST.source_id:ACTION_MANIFEST.license_id,SECURITY_MASTER_MANIFEST.source_id:SECURITY_MASTER_MANIFEST.license_id}.get(source_id)
    return PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,license_id=license_id,retention_class="standard")
@dataclass(frozen=True)
class QuantProjectionBundle:
    exact:tuple=();lexical:tuple=();entities:tuple=();assertions:tuple=();structured_rows:tuple=()

def _common(d,revision_uid,source_id,manifest):
    available=d.get("available_at") or d.get("accepted_at") or d.get("realtime_start")
    vf=d.get("valid_from") or d.get("filed_at") or d.get("observation_date") or d.get("trading_date") or d.get("effective_date") or d.get("alias_from")
    vt=d.get("valid_to") or d.get("alias_to")
    return {"revision_uid":revision_uid,"revision_order":int((_dt(available) or datetime(1970,1,1,tzinfo=UTC)).timestamp()),"available_at":None if _dt(available) is None else _dt(available).isoformat().replace("+00:00","Z"),"valid_from":None if _dt(vf) is None else _dt(vf).isoformat().replace("+00:00","Z"),"valid_to":None if _dt(vt) is None else _dt(vt).isoformat().replace("+00:00","Z"),"system_manifest_id":manifest,"dependency_available_at_max":None,"dependency_manifest_id":None,"tenant_id":"public","domain":"quant","source_id":source_id,"access_label":"public"}

class QuantProjectionProjector:
    def project_one(self,*,normalized_bytes,artifact_uid,revision_uid,object_uid,source_id,system_manifest_id="quant-fixture"):
        d=json.loads(normalized_bytes.decode());kind=d["kind"];policy=_policy(source_id);exact=[];lex=[];entities=[];assertions=[];rows=[]
        c=_common(d,revision_uid,source_id,system_manifest_id);available=_dt(c["available_at"]);vf=_dt(c["valid_from"]);vt=_dt(c["valid_to"])
        if kind=="sec-company":
            cik=d["cik"];loc=JsonPointerLocator("/cik")
            exact.append(ExactRecord(revision_uid,object_uid,"cik","legal-entity",cik,"quant",source_id,"public",AccessLabel.PUBLIC,available,vf,vt,json.dumps(locator_to_data(loc),sort_keys=True,separators=(",",":")),d.get("name") or cik))
            entities.append(CanonicalEntity("cik","legal-entity",cik,d.get("name") or cik,policy,source_id,available,vf,vt,system_manifest_id))
        elif kind=="sec-filing":
            accn=d["accession"];loc=JsonPointerLocator("/accession")
            exact.append(ExactRecord(revision_uid,object_uid,"sec-accession","sec-filing",accn,"quant",source_id,"public",AccessLabel.PUBLIC,available,vf,vt,json.dumps(locator_to_data(loc),sort_keys=True,separators=(",",":")),accn))
            filing=CanonicalEntity("sec-accession","sec-filing",accn,accn,policy,source_id,available,vf,vt,system_manifest_id);issuer=CanonicalEntity("cik","legal-entity",d["cik"],d.get("company_name") or d["cik"],policy,source_id,available,None,None,system_manifest_id);entities.extend((filing,issuer))
            assertions.append(SourceAssertion(revision_uid,filing.ref,"filed_by",issuer.ref,(AssertionQualifier("form",str(d.get("form"))),),(ProvenanceRef(revision_uid,JsonPointerLocator("/cik")),),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=policy,available_at=available,valid_from=vf,system_manifest_id=system_manifest_id))
            if d.get("amends"):
                prior=CanonicalEntity("sec-accession","sec-filing",d["amends"],d["amends"],policy,source_id,available,None,None,system_manifest_id);entities.append(prior)
                assertions.append(SourceAssertion(revision_uid,filing.ref,"amends",prior.ref,(AssertionQualifier("form",str(d.get("form"))),),(ProvenanceRef(revision_uid,JsonPointerLocator("/amends")),),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=policy,available_at=available,valid_from=vf,system_manifest_id=system_manifest_id))
            chunker=ComponentFingerprint("sec-filing-section","1")
            for section in d.get("sections",()):
                locator=CanonicalPassageLocator("sec-filing-section",section["source_coordinate"]);passage=Passage(artifact_uid,revision_uid,locator,section["text"],chunker,EpistemicMetadata(EpistemicKind.SOURCE_CLAIM))
                lex.append(LexicalDocument(passage.passage_uid,revision_uid,object_uid,"sec-accession","sec-filing",accn,"quant",source_id,"public",AccessLabel.PUBLIC,available,vf,vt,json.dumps(locator_to_data(locator),sort_keys=True,separators=(",",":")),section["text"],normalize_search_text(section["text"]),normalize_search_text(f"{accn} {d.get('form')} {section.get('title')}"),"unicode61/1"))
            for fact in d.get("facts",()):
                rows.append(("quant_fundamental",c|{"cik":d["cik"],"accession":accn,"form":d.get("form"),"tag":fact["tag"],"namespace":fact["namespace"],"value":fact.get("value"),"unit":fact["unit"],"currency":fact.get("currency"),"period_start":fact.get("period_start"),"period_end":fact.get("period_end"),"reporting_basis":fact.get("reporting_basis"),"context_id":fact.get("context_id"),"source_coordinate":fact["source_coordinate"],"amendment":bool(d.get("amendment"))}))
        elif kind=="macro-observation":
            rows.append(("quant_macro",c|{"series_id":d["series_id"],"observation_date":d["observation_date"],"value":d.get("value"),"unit":d["unit"],"realtime_start":d["realtime_start"],"realtime_end":d.get("realtime_end"),"frequency":d.get("frequency"),"seasonal_adjustment":d.get("seasonal_adjustment"),"source_coordinate":d["source_coordinate"]}))
        elif kind=="market-price":
            rows.append(("quant_prices",c|{"security_id":d["security_id"],"ticker":d["ticker"],"exchange":d["exchange"],"trading_date":d["trading_date"],"close":d["close"],"currency":d["currency"],"calendar":d["calendar"],"timezone":d["timezone"],"adjusted":bool(d["adjusted"]),"provider":d["provider"],"corporate_action_version":d.get("corporate_action_version"),"source_coordinate":d["source_coordinate"]}))
        elif kind=="corporate-action":
            rows.append(("quant_corporate_actions",c|{"security_id":d["security_id"],"action_type":d["action_type"],"effective_date":d["effective_date"],"ratio":d["ratio"],"currency":d.get("currency"),"provider":d["provider"],"source_coordinate":d["source_coordinate"]}))
        elif kind=="security-master":
            security=CanonicalEntity("security","security",d["security_id"],d["security_id"],policy,source_id,available,vf,vt,system_manifest_id);issuer=CanonicalEntity("cik","legal-entity",d["issuer_cik"],d["issuer_cik"],policy,source_id,available,None,None,system_manifest_id);entities.extend((security,issuer))
            assertions.append(SourceAssertion(revision_uid,security.ref,"issued_by",issuer.ref,(AssertionQualifier("exchange",d["exchange"]),),(ProvenanceRef(revision_uid,JsonPointerLocator("/issuer_cik")),),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=policy,available_at=available,valid_from=vf,valid_to=vt,system_manifest_id=system_manifest_id))
            rows.append(("quant_security_alias",c|{"security_id":d["security_id"],"issuer_cik":d["issuer_cik"],"ticker":d["ticker"],"exchange":d["exchange"],"alias_from":d["alias_from"],"alias_to":d.get("alias_to"),"listed_from":d.get("listed_from"),"listed_to":d.get("listed_to"),"delisted_at":d.get("delisted_at")}))
            rows.append(("quant_universe",c|{"universe_id":d["universe_id"],"security_id":d["security_id"],"member_from":d["member_from"],"member_to":d.get("member_to"),"delisted_at":d.get("delisted_at")}))
        return QuantProjectionBundle(tuple(exact),tuple(lex),tuple(entities),tuple(assertions),tuple(rows))

class QuantProjectionRebuilder:
    def __init__(self,metadata_store,object_store,projector=None):self.meta=metadata_store;self.objects=object_store;self.projector=projector or QuantProjectionProjector()
    def rebuild(self,source_ids=("sec-edgar-fixture","fred-alfred-fixture","licensed-price-file-fixture","licensed-corporate-action-file-fixture","security-master-fixture"),system_manifest_id="quant-fixture"):
        refs={r.digest:r for r in self.objects.iter_refs()};exact=[];lex=[];entities=[];assertions=[];rows=[]
        for artifact_uid,revision_uid,digest,retention,object_uid,source_id,stable_id,object_type,revoked in self.meta.projection_artifacts(source_ids):
            if revoked or digest not in refs:continue
            b=self.projector.project_one(normalized_bytes=self.objects.get(refs[digest]),artifact_uid=artifact_uid,revision_uid=revision_uid,object_uid=object_uid,source_id=source_id,system_manifest_id=system_manifest_id)
            exact.extend(b.exact);lex.extend(b.lexical);entities.extend(b.entities);assertions.extend(b.assertions);rows.extend(b.structured_rows)
        return QuantProjectionBundle(tuple(exact),tuple(lex),tuple(sorted({e.entity_uid:e for e in entities}.values(),key=lambda e:e.entity_uid)),tuple(assertions),tuple(rows))
