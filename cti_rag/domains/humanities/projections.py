from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime,timezone
from cti_rag.contracts import AccessLabel,AssertionQualifier,CanonicalPassageLocator,ComponentFingerprint,EpistemicKind,EpistemicMetadata,IiifLocator,JsonPointerLocator,Passage,PolicyLabels,ProcessingClass,ProvenanceRef,SourceAssertion,TeiLocator,locator_to_data
from cti_rag.graph import CanonicalEntity
from cti_rag.retrieval import ExactRecord,LexicalDocument,normalize_search_text
from .analyzers import analyzer_profile
from .sources import GUTENBERG_MANIFEST,TEI_MANIFEST,IIIF_MANIFEST
UTC=timezone.utc
def _dt(v):
    if not v:return None
    return datetime.fromisoformat(str(v).replace("Z","+00:00")).astimezone(UTC)
def _policy(source_id):
    lid={GUTENBERG_MANIFEST.source_id:GUTENBERG_MANIFEST.license_id,TEI_MANIFEST.source_id:TEI_MANIFEST.license_id,IIIF_MANIFEST.source_id:IIIF_MANIFEST.license_id}.get(source_id)
    return PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,license_id=lid,retention_class="standard")
def _locator(d):
    if d["kind"]=="canonical":return CanonicalPassageLocator(d["scheme"],d["value"])
    if d["kind"]=="tei":return TeiLocator(d["xpath"],d.get("canonical_id"))
    if d["kind"]=="iiif":return IiifLocator(d["canvas_id"],int(d["page"]),None if d.get("bbox") is None else tuple(float(v) for v in d["bbox"]))
    raise ValueError("unsupported humanities locator")
def _exact_namespace(identifier):
    if identifier.startswith("WORK:"):return ("work-id","work")
    if identifier.startswith("EDITION:"):return ("edition-id","edition")
    if identifier.startswith("PASSAGE:"):return ("passage-id","passage")
    if identifier.startswith("urn:cts:"):return ("cts","passage")
    return None
@dataclass(frozen=True)
class HumanitiesProjectionBundle:
    exact:tuple=();lexical:tuple=();annotations:tuple=();entities:tuple=();assertions:tuple=();structured_rows:tuple=()

def _date_fields(d):
    interval=d.get("date_interval") or {}
    start=interval.get("start");end=interval.get("end_exclusive");precision=interval.get("precision","uncertain");label=interval.get("label")
    vf=_dt(start+"T00:00:00Z") if start and precision=="exact_date" else None
    vt=_dt(end+"T00:00:00Z") if end and precision=="exact_date" else None
    return start,end,precision,label,vf,vt
def _common(d,revision_uid,source_id,manifest):
    available=d.get("available_at");start,end,precision,label,vf,vt=_date_fields(d)
    return {"revision_uid":revision_uid,"revision_order":int((_dt(available) or datetime(1970,1,1,tzinfo=UTC)).timestamp()),"available_at":available,
            "valid_from":None if vf is None else vf.isoformat().replace("+00:00","Z"),"valid_to":None if vt is None else vt.isoformat().replace("+00:00","Z"),
            "system_manifest_id":manifest,"dependency_available_at_max":None,"dependency_manifest_id":None,"tenant_id":"public","domain":"humanities","source_id":source_id,"access_label":"public"}

class HumanitiesProjectionProjector:
    def project_one(self,*,normalized_bytes,artifact_uid,revision_uid,object_uid,source_id,system_manifest_id="humanities-fixture"):
        d=json.loads(normalized_bytes.decode());kind=d["kind"];policy=_policy(source_id);available=_dt(d.get("available_at"));exact=[];lex=[];ann=[];entities=[];assertions=[];rows=[]
        if kind=="work":
            ns,obj=_exact_namespace(d["id"]);loc=JsonPointerLocator("/id")
            exact.append(ExactRecord(revision_uid,object_uid,ns,obj,d["id"],"humanities",source_id,"public",AccessLabel.PUBLIC,available,None,None,json.dumps(locator_to_data(loc),sort_keys=True,separators=(",",":")),d.get("title") or d["id"]))
            entities.append(CanonicalEntity(ns,obj,d["id"],d.get("title") or d["id"],policy,source_id,available,None,None,system_manifest_id))
            return HumanitiesProjectionBundle(tuple(exact),(),(),tuple(entities),(),())
        if kind!="edition":raise ValueError("unsupported normalized humanities kind")
        start,end,precision,label,vf,vt=_date_fields(d);edition_id=d["id"];work_id=d["work_id"]
        ens,eobj=_exact_namespace(edition_id);w_ns,w_obj=_exact_namespace(work_id);eloc=JsonPointerLocator("/id")
        exact.append(ExactRecord(revision_uid,object_uid,ens,eobj,edition_id,"humanities",source_id,"public",AccessLabel.PUBLIC,available,vf,vt,json.dumps(locator_to_data(eloc),sort_keys=True,separators=(",",":")),d.get("label") or edition_id))
        edition=CanonicalEntity(ens,eobj,edition_id,d.get("label") or edition_id,policy,source_id,available,vf,vt,system_manifest_id);work=CanonicalEntity(w_ns,w_obj,work_id,work_id,policy,source_id,available,None,None,system_manifest_id);entities.extend((edition,work))
        assertions.append(SourceAssertion(revision_uid,edition.ref,"edition_of",work.ref,(AssertionQualifier("relationship","edition"),),(ProvenanceRef(revision_uid,JsonPointerLocator("/work_id")),),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=policy,available_at=available,valid_from=vf,valid_to=vt,system_manifest_id=system_manifest_id))
        if d.get("witness_id"):
            witness=CanonicalEntity("witness","witness",d["witness_id"],d["witness_id"],policy,source_id,available,vf,vt,system_manifest_id);entities.append(witness)
            assertions.append(SourceAssertion(revision_uid,witness.ref,"witness_of",edition.ref,(AssertionQualifier("relationship","physical_or_textual_witness"),),(ProvenanceRef(revision_uid,JsonPointerLocator("/witness_id")),),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=policy,available_at=available,valid_from=vf,valid_to=vt,system_manifest_id=system_manifest_id))
        trans=d.get("translation")
        if trans and trans.get("edition_id"):
            t=CanonicalEntity("edition-id","edition",trans["edition_id"],trans["edition_id"],policy,source_id,available,None,None,system_manifest_id);entities.append(t)
            assertions.append(SourceAssertion(revision_uid,t.ref,"translation_of",edition.ref,(AssertionQualifier("language",str(trans.get("language") or "")),),(ProvenanceRef(revision_uid,JsonPointerLocator("/translation/source_edition")),),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=policy,available_at=available,system_manifest_id=system_manifest_id))
        if d.get("edition_type")=="newspaper":
            article=CanonicalEntity("article","article",d["article_id"],d["article_id"],policy,source_id,available,vf,vt,system_manifest_id);page=CanonicalEntity("page","page",d["page_id"],d["page_id"],policy,source_id,available,vf,vt,system_manifest_id);inst=CanonicalEntity("institution","institution",d["institution_id"],d["institution_id"],policy,source_id,available,None,None,system_manifest_id);entities.extend((article,page,inst))
            assertions.append(SourceAssertion(revision_uid,article.ref,"article_on_page",page.ref,(AssertionQualifier("edition",edition_id),),(ProvenanceRef(revision_uid,JsonPointerLocator("/article_id")),),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=policy,available_at=available,valid_from=vf,valid_to=vt,system_manifest_id=system_manifest_id))
            assertions.append(SourceAssertion(revision_uid,article.ref,"held_by",inst.ref,(AssertionQualifier("institutional_provenance","holding_institution"),),(ProvenanceRef(revision_uid,JsonPointerLocator("/institution_id")),),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),source_id=source_id,policy=policy,available_at=available,system_manifest_id=system_manifest_id))
        for i,p in enumerate(d.get("passages",())):
            loc=_locator(p["locator"]);pid=p["id"];role=p["role"];profile=analyzer_profile(p["language"]);ep=EpistemicMetadata(EpistemicKind.SOURCE_CLAIM if role=="primary_text" else EpistemicKind.INTERPRETATION,method=role)
            passage=Passage(artifact_uid,revision_uid,loc,p["original"],ComponentFingerprint("humanities-structure","1"),ep)
            nsobj=_exact_namespace(pid)
            if nsobj and role=="primary_text":
                ns,obj=nsobj;exact.append(ExactRecord(revision_uid,object_uid,ns,obj,pid,"humanities",source_id,"public",AccessLabel.PUBLIC,available,vf,vt,json.dumps(locator_to_data(loc),sort_keys=True,separators=(",",":")),p["original"]))
            doc=LexicalDocument(passage.passage_uid,revision_uid,object_uid,(nsobj or ("humanities-note","annotation"))[0],(nsobj or ("humanities-note","annotation"))[1],pid,"humanities",source_id,"public",AccessLabel.PUBLIC,available,vf,vt,json.dumps(locator_to_data(loc),sort_keys=True,separators=(",",":")),p["original"],normalize_search_text(p["normalized"]),normalize_search_text(f"{d.get('label','')} {edition_id} {work_id} {p['language']} {role}"),profile.analyzer_version or "unsupported")
            if role=="primary_text" and profile.supported:lex.append(doc)
            else:ann.append(doc)
            rows.append(("humanities_passages",_common(d,revision_uid,source_id,system_manifest_id)|{"work_id":work_id,"edition_id":edition_id,"passage_id":pid,"role":role,"language":p["language"],"rights":d.get("rights"),"transcription_quality":p.get("transcription_quality") or "unknown","ocr_confidence":p.get("ocr_confidence"),"date_start":start,"date_end_exclusive":end,"date_precision":precision,"date_label":label,"original_text":p["original"],"normalized_text":p["normalized"],"locator_json":json.dumps(locator_to_data(loc),sort_keys=True,separators=(",",":"))}))
        return HumanitiesProjectionBundle(tuple(exact),tuple(lex),tuple(ann),tuple(entities),tuple(assertions),tuple(rows))

class HumanitiesProjectionRebuilder:
    def __init__(self,metadata_store,object_store,projector=None):self.meta=metadata_store;self.objects=object_store;self.projector=projector or HumanitiesProjectionProjector()
    def rebuild(self,source_ids=("gutenberg-public-domain-fixture","tei-perseus-style-fixture","chronicling-america-iiif-fixture"),system_manifest_id="humanities-fixture"):
        refs={r.digest:r for r in self.objects.iter_refs()};exact=[];lex=[];ann=[];entities=[];assertions=[];rows=[]
        for artifact_uid,revision_uid,digest,retention,object_uid,source_id,stable_id,object_type,revoked in self.meta.projection_artifacts(source_ids):
            if revoked or digest not in refs:continue
            b=self.projector.project_one(normalized_bytes=self.objects.get(refs[digest]),artifact_uid=artifact_uid,revision_uid=revision_uid,object_uid=object_uid,source_id=source_id,system_manifest_id=system_manifest_id)
            exact.extend(b.exact);lex.extend(b.lexical);ann.extend(b.annotations);entities.extend(b.entities);assertions.extend(b.assertions);rows.extend(b.structured_rows)
        return HumanitiesProjectionBundle(tuple(exact),tuple(lex),tuple(ann),tuple(sorted({e.entity_uid:e for e in entities}.values(),key=lambda e:e.entity_uid)),tuple(assertions),tuple(rows))
