"""Canonical normalization for objects imported read-only from OpenCTI."""
from __future__ import annotations
import json
from datetime import datetime,timezone
from cti_rag.contracts import (
    AccessLabel,AvailabilityBasis,IdentityAttribute,PolicyLabels,ProcessingClass,
    TemporalMetadata,canonical_json_bytes,
)
from cti_rag.ingestion import SourceManifest
from cti_rag.ports import NormalizedRecord

UTC=timezone.utc
_TLP={
    "TLP:CLEAR":AccessLabel.PUBLIC,"TLP:WHITE":AccessLabel.PUBLIC,
    "TLP:GREEN":AccessLabel.INTERNAL,
    "TLP:AMBER":AccessLabel.CONFIDENTIAL,"TLP:AMBER+STRICT":AccessLabel.CONFIDENTIAL,
    "TLP:RED":AccessLabel.RESTRICTED,
}
_ORDER={AccessLabel.PUBLIC:0,AccessLabel.INTERNAL:1,AccessLabel.CONFIDENTIAL:2,AccessLabel.RESTRICTED:3,AccessLabel.PRIVATE:4}

OPENCTI_MANIFEST=SourceManifest(
    "opencti-read","cybersecurity","opencti-stix-2.1","stix-object-or-relationship",
    "updated_at+stix_modified+content_digest",None,AccessLabel.RESTRICTED,ProcessingClass.LOCAL_ONLY,
    "standard","bounded GraphQL cursor synchronization","revoked/deprecated/absence tombstone",
    AvailabilityBasis.UPSTREAM_METADATA,("exact","lexical","dense","graph","structured"),
    source_uri=None,license_notice="Rights and source attribution remain object-specific and must be preserved from imported STIX/OpenCTI metadata.",
    connector_fingerprint="opencti-read-connector/1",parser_fingerprint="opencti-import-normalizer/1",
)

def _dt(value):
    if value in (None,""):return None
    try:return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(UTC)
    except ValueError as exc:raise ValueError("invalid OpenCTI/STIX timestamp") from exc

def _markings(metadata,tenant_id):
    rows=metadata.get("objectMarking") or ()
    if type(rows) is not list:raise ValueError("invalid OpenCTI objectMarking shape")
    labels=[];preserved=[]
    for row in rows:
        if type(row) is not dict:raise ValueError("invalid OpenCTI marking")
        definition_type=str(row.get("definition_type","")).strip().upper()
        definition=str(row.get("definition","")).strip().upper().replace(" ","")
        standard_id=str(row.get("standard_id") or row.get("id") or "").strip()
        preserved.append(standard_id or definition)
        if definition_type!="TLP" or definition not in _TLP:
            raise ValueError("unsupported mandatory OpenCTI marking restriction")
        labels.append(_TLP[definition])
    access=max(labels,key=lambda v:_ORDER[v]) if labels else AccessLabel.PUBLIC
    processing=ProcessingClass.LOCAL_OR_APPROVED_REMOTE if access==AccessLabel.PUBLIC else ProcessingClass.LOCAL_ONLY
    return PolicyLabels(tenant_id,access,processing,markings=tuple(dict.fromkeys(preserved)))

class OpenCTIImportedStixNormalizer:
    normalizer_fingerprint="opencti-import-normalizer/1"
    def __init__(self,tenant_id="public"):
        if not str(tenant_id).strip():raise ValueError("OpenCTI tenant_id required")
        self.tenant_id=str(tenant_id)

    def normalize(self,record):
        try:wrapper=json.loads(record.raw_bytes.decode("utf-8"))
        except Exception as exc:raise ValueError("invalid OpenCTI wrapper JSON") from exc
        if type(wrapper) is not dict or set(wrapper)!={"opencti","stix"}:raise ValueError("invalid OpenCTI wrapper schema")
        metadata=wrapper["opencti"];stix=wrapper["stix"]
        if type(metadata) is not dict or type(stix) is not dict:raise ValueError("invalid OpenCTI wrapper members")
        stable=str(stix.get("id","")).strip();typ=str(stix.get("type","")).strip()
        if not stable or stable.count("--")!=1 or not typ:raise ValueError("invalid imported STIX identity")
        if str(stix.get("spec_version","2.1"))!="2.1":raise ValueError("unsupported imported STIX version")
        if str(metadata.get("standard_id") or stable)!=stable:raise ValueError("OpenCTI standard_id differs from exported STIX id")
        policy=_markings(metadata,self.tenant_id)
        created=_dt(stix.get("created") or metadata.get("created_at") or metadata.get("updated_at"))
        modified=_dt(stix.get("modified") or metadata.get("updated_at") or stix.get("created"))
        available=_dt(metadata.get("updated_at") or stix.get("modified") or stix.get("created"))
        if created is None or modified is None or available is None:raise ValueError("imported OpenCTI object lacks temporal metadata")
        valid_from=_dt(stix.get("valid_from") or stix.get("first_seen")) or created
        valid_to=_dt(stix.get("valid_until") or stix.get("last_seen"))
        external=stix.get("external_references")
        if external is None:external=[]
        if type(external) is not list:raise ValueError("invalid STIX external_references")
        normalized={
            "kind":"opencti-imported-stix","id":stable,"stix_type":typ,
            "name":stix.get("name") or stix.get("value"),"description":stix.get("description"),
            "relationship_type":stix.get("relationship_type"),"source_ref":stix.get("source_ref"),"target_ref":stix.get("target_ref"),
            "external_references":external,
            "opencti":{"id":metadata.get("id"),"standard_id":metadata.get("standard_id"),"entity_type":metadata.get("entity_type"),"created_at":metadata.get("created_at"),"updated_at":metadata.get("updated_at"),"object_marking":metadata.get("objectMarking") or (), "external_references":metadata.get("externalReferences"),"created_by":metadata.get("createdBy")},
            "assertion_origin":"imported_source","locally_extracted_hypothesis":False,
            "revoked":bool(stix.get("revoked",False)),"deprecated":bool(stix.get("x_mitre_deprecated",False)),
        }
        identities=[IdentityAttribute("stix_id",stable)]
        opencti_id=str(metadata.get("id") or "").strip()
        if opencti_id:identities.append(IdentityAttribute("opencti_id",opencti_id))
        temporal=TemporalMetadata(created,modified,published_at=created,available_at=available,available_at_basis=AvailabilityBasis.UPSTREAM_METADATA,valid_from=valid_from,valid_to=valid_to)
        return NormalizedRecord(stable,typ,canonical_json_bytes(normalized),tuple(identities),temporal,policy,"opencti-imported-stix/1",record.upstream_version)
