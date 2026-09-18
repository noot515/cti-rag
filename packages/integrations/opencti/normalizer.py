"""Normalize complete OpenCTI captures into existing CTI evidence contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from packages.domains.cti import CtiDomainAdapter, CtiChunk
from packages.domains.cti.markings import CtiMarking, to_policy_metadata
from packages.domains.cti.relations import normalize_relation
from packages.domains.cti.schema import (
    CtiAttackPatternData,
    CtiNormalizedEvidenceBatch,
    CtiObject,
    CtiQuarantinedRecord,
    CtiRelationship,
    CtiReportData,
    CtiVulnerabilityData,
)
from packages.evidence.ids import (
    canonical_hash,
    object_uid,
    relation_revision_uid,
    relation_uid,
    revision_uid,
)
from packages.evidence.provenance import canonical_revision_projection
from packages.evidence.schema import EvidenceExtension, EvidencePolicyMetadata, LifecycleState, SourceRef

from .reader import CompleteCapture, CapturedRecord, raw_payload_bytes


NORMALIZER_VERSION = "opencti-capture-normalizer-v1"


@dataclass(frozen=True)
class NormalizedOpenCTICapture:
    batch: CtiNormalizedEvidenceBatch
    raw_payloads: dict[str, bytes]
    quarantine_counts: dict[str, int]
    source_snapshot_id: str


def _nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        edges = value.get("edges")
        if isinstance(edges, list):
            return [
                edge["node"]
                for edge in edges
                if isinstance(edge, dict) and isinstance(edge.get("node"), dict)
            ]
    return []


def _source_id(payload: Mapping[str, Any]) -> str:
    value = payload.get("standard_id") or payload.get("id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("OpenCTI object lacks standard_id/id")
    return value.strip()


def _marking(record: Mapping[str, Any]) -> CtiMarking | None:
    ref = record.get("standard_id") or record.get("id")
    definition_type = record.get("definition_type")
    definition = record.get("definition")
    if not isinstance(ref, str) or not ref or not isinstance(definition_type, str) or not definition_type:
        return None
    if definition_type.casefold() == "tlp" and isinstance(definition, str):
        text = definition.strip()
        if text.casefold().startswith("tlp:"):
            definition = text.split(":", 1)[1]
    try:
        return CtiMarking(
            marking_ref=ref,
            definition_type=definition_type,
            definition=definition,
        )
    except Exception:
        return None


def _policy(
    payload: Mapping[str, Any],
    *,
    source_instance: str,
    sanitized_public_fixture: bool,
) -> tuple[tuple[CtiMarking, ...], EvidencePolicyMetadata]:
    markings = tuple(
        item
        for item in (_marking(raw) for raw in _nodes(payload.get("objectMarking")))
        if item is not None
    )
    if not markings and sanitized_public_fixture:
        markings = (
            CtiMarking(
                marking_ref="opencti-sanitized-tlp-clear",
                definition_type="TLP",
                definition="CLEAR",
            ),
        )
    if not markings:
        return (), EvidencePolicyMetadata(
            source_instances=(source_instance,),
            unresolved_markings=True,
        )
    policy = to_policy_metadata(
        source_instances=(source_instance,),
        markings=markings,
        declared_marking_refs=(item.marking_ref for item in markings),
    )
    return markings, policy


def _external_ids(kind: str, payload: Mapping[str, Any], adapter: CtiDomainAdapter):
    candidates: list[str] = []
    if kind == "attack_pattern":
        if payload.get("x_mitre_id"):
            candidates.append(str(payload["x_mitre_id"]))
    elif kind == "vulnerability":
        if payload.get("name"):
            candidates.append(str(payload["name"]))
        if payload.get("x_opencti_cwe"):
            raw = payload["x_opencti_cwe"]
            if isinstance(raw, list):
                candidates.extend(str(item) for item in raw)
            else:
                candidates.append(str(raw))
    for reference in _nodes(payload.get("externalReferences")):
        if reference.get("external_id"):
            candidates.append(str(reference["external_id"]))
    seen: set[tuple[str, str]] = set()
    result = []
    for candidate in candidates:
        for identifier in adapter.parse_identifiers(candidate):
            key = (identifier.namespace, identifier.value)
            if key not in seen:
                result.append(identifier)
                seen.add(key)
    return tuple(result)


def _object_type(kind: str, payload: Mapping[str, Any]) -> str:
    if kind == "vulnerability":
        return "vulnerability"
    if kind == "report":
        return "report"
    if kind == "attack_pattern":
        return "technique" if payload.get("x_mitre_id") else "attack-pattern"
    raise ValueError(f"unsupported captured object kind: {kind}")


def _family(kind: str, payload: Mapping[str, Any], external_ids):
    if kind == "vulnerability":
        cve = next((item.value for item in external_ids if item.namespace == "cve"), None)
        return CtiVulnerabilityData(cve_id=cve)
    if kind == "attack_pattern":
        capec = next((item.value for item in external_ids if item.namespace == "capec"), None)
        attack = next((item.value for item in external_ids if item.namespace == "attack"), None)
        return CtiAttackPatternData(capec_id=capec, attack_technique_id=attack)
    if kind == "report":
        refs = []
        for item in _nodes(payload.get("objects")):
            value = item.get("standard_id") or item.get("id")
            if isinstance(value, str) and value:
                refs.append(value)
        return CtiReportData(object_refs=tuple(dict.fromkeys(refs)))
    raise ValueError(kind)


def _source_ref(
    record: CapturedRecord,
    *,
    source_snapshot_id: str,
    source_uri: str | None,
) -> SourceRef:
    return SourceRef(
        domain="cti",
        source_instance=record.source_instance,
        source_object_id=record.source_object_id,
        upstream_origin=f"opencti:{record.kind}",
        source_uri=source_uri,
        raw_payload_sha256=record.raw_payload.sha256,
        source_snapshot_id=source_snapshot_id,
        normalizer_version=NORMALIZER_VERSION,
    )


def _lifecycle(payload: Mapping[str, Any]) -> LifecycleState:
    return LifecycleState.REVOKED if payload.get("revoked") is True else LifecycleState.ACTIVE


def _semantic_object(payload: Mapping[str, Any]) -> dict[str, Any]:
    # updated_at is intentionally omitted: it is OpenCTI platform ordering/capture
    # metadata. STIX modified remains semantic and can create a real revision.
    keys = (
        "standard_id", "entity_type", "spec_version", "created", "modified",
        "name", "description", "content", "published", "revoked", "confidence",
        "x_mitre_id", "x_opencti_cwe", "x_opencti_aliases",
    )
    semantic = {key: payload[key] for key in keys if key in payload}
    semantic["custom_fields"] = {
        key: value
        for key, value in payload.items()
        if key.startswith("x_") and key not in semantic
    }
    return semantic


def _extension(payload: Mapping[str, Any]) -> EvidenceExtension:
    return EvidenceExtension(
        type_name="opencti-capture",
        schema_version="v1",
        data={
            "opencti_internal_id": str(payload.get("id") or ""),
            "updated_at": str(payload.get("updated_at") or ""),
            "entity_type": str(payload.get("entity_type") or ""),
        },
    )


def _normalize_object(
    record: CapturedRecord,
    *,
    scope_id: str,
    source_snapshot_id: str,
    source_uri: str | None,
    sanitized_public_fixture: bool,
    adapter: CtiDomainAdapter,
) -> CtiObject:
    payload = record.payload
    source_id = _source_id(payload)
    uid = object_uid("cti", record.source_instance, source_id)
    external_ids = _external_ids(record.kind, payload, adapter)
    markings, policy = _policy(
        payload,
        source_instance=record.source_instance,
        sanitized_public_fixture=sanitized_public_fixture,
    )
    source = _source_ref(record, source_snapshot_id=source_snapshot_id, source_uri=source_uri)
    projection = canonical_revision_projection(
        source_instance=record.source_instance,
        source_object_id=source_id,
        upstream_origin=f"opencti:{record.kind}",
        source_uri=source_uri,
        normalizer_version=NORMALIZER_VERSION,
        semantic_fields=_semantic_object(payload),
        policy_fields=policy.model_dump(mode="json"),
        evidence_locators=(source_id,),
    )
    revision = revision_uid(uid, projection)
    aliases_raw = payload.get("aliases") or payload.get("x_opencti_aliases") or ()
    aliases = tuple(str(item) for item in aliases_raw) if isinstance(aliases_raw, list) else ()
    return CtiObject(
        uid=uid,
        revision_uid=revision,
        scope_id=scope_id,
        object_type=_object_type(record.kind, payload),
        name=str(payload.get("name")) if payload.get("name") is not None else None,
        description=str(payload.get("description") or payload.get("content")) if (payload.get("description") or payload.get("content")) is not None else None,
        external_ids=external_ids,
        aliases=aliases,
        source_refs=(source,),
        created_at=payload.get("created"),
        modified_at=payload.get("modified"),
        lifecycle_state=_lifecycle(payload),
        extension_type="cti",
        extension=_extension(payload),
        policy=policy,
        stix_family="sdo",
        stix_type=str(payload.get("entity_type") or "").casefold(),
        stix_id=str(payload.get("standard_id")) if payload.get("standard_id") else None,
        revoked=payload.get("revoked") is True,
        confidence=payload.get("confidence") if isinstance(payload.get("confidence"), int) else None,
        marking_refs=tuple(item.marking_ref for item in markings),
        markings=markings,
        family_data=_family(record.kind, payload, external_ids),
    )


def _endpoint_keys(payload: Mapping[str, Any]) -> tuple[str, ...]:
    values = []
    for key in ("standard_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    return tuple(values)


def _normalize_relation(
    record: CapturedRecord,
    *,
    scope_id: str,
    source_snapshot_id: str,
    source_uri: str | None,
    sanitized_public_fixture: bool,
    endpoint_uids: Mapping[str, str],
) -> CtiRelationship:
    payload = record.payload
    source_node = payload.get("from")
    target_node = payload.get("to")
    if not isinstance(source_node, dict) or not isinstance(target_node, dict):
        raise ValueError("OpenCTI relationship lacks from/to objects")
    source_uid = next((endpoint_uids[key] for key in _endpoint_keys(source_node) if key in endpoint_uids), None)
    target_uid = next((endpoint_uids[key] for key in _endpoint_keys(target_node) if key in endpoint_uids), None)
    if source_uid is None or target_uid is None:
        raise LookupError("OpenCTI relationship endpoint is not present in the complete captured object set")
    original = str(payload.get("relationship_type") or "")
    normalized = normalize_relation(original)
    upstream_id = _source_id(payload)
    markings, policy = _policy(
        payload,
        source_instance=record.source_instance,
        sanitized_public_fixture=sanitized_public_fixture,
    )
    source_ref = _source_ref(record, source_snapshot_id=source_snapshot_id, source_uri=source_uri)
    uid = relation_uid(
        domain="cti",
        source_instance=record.source_instance,
        source_record_id=upstream_id,
        source_object_uid=source_uid,
        target_object_uid=target_uid,
        normalized_relation=normalized,
        upstream_relation_id=upstream_id,
    )
    semantic = {
        key: payload[key]
        for key in (
            "standard_id", "relationship_type", "description", "start_time", "stop_time",
            "created", "modified", "revoked", "confidence",
        )
        if key in payload
    }
    projection = canonical_revision_projection(
        source_instance=record.source_instance,
        source_object_id=upstream_id,
        upstream_origin="opencti:relationship",
        source_uri=source_uri,
        normalizer_version=NORMALIZER_VERSION,
        semantic_fields=semantic,
        policy_fields=policy.model_dump(mode="json"),
        evidence_locators=(upstream_id,),
    )
    return CtiRelationship(
        uid=uid,
        revision_uid=relation_revision_uid(uid, projection),
        scope_id=scope_id,
        source_object_uid=source_uid,
        target_object_uid=target_uid,
        original_relation=original,
        normalized_relation=normalized,
        assertion_kind="explicit",
        evidence_refs=(source_ref,),
        lifecycle_state=_lifecycle(payload),
        extension_type="cti-relationship",
        extension=_extension(payload),
        policy=policy,
        relationship_kind=normalized,
        marking_refs=tuple(item.marking_ref for item in markings),
        markings=markings,
        producer_confidence=payload.get("confidence") if isinstance(payload.get("confidence"), int) else None,
    )


def normalize_complete_capture(
    capture: CompleteCapture,
    *,
    scope_id: str,
    source_uri: str | None,
    sanitized_public_fixture: bool,
) -> NormalizedOpenCTICapture:
    if not capture.complete:
        raise ValueError("partial OpenCTI capture cannot be normalized for publication")
    # Capture interval belongs in the replay/inventory ledger, not semantic
    # source identity. Unchanged complete scans therefore replay idempotently.
    source_snapshot_id = canonical_hash(
        [
            "opencti-content-snapshot-v2",
            capture.source_instance,
            capture.platform_version,
            sorted(
                (record.kind, record.source_object_id, record.raw_payload.sha256)
                for record in capture.records
            ),
        ]
    )
    adapter = CtiDomainAdapter()
    objects: list[CtiObject] = []
    relations: list[CtiRelationship] = []
    quarantined: list[CtiQuarantinedRecord] = []
    raw_payloads: dict[str, bytes] = {}

    object_records = [record for record in capture.records if record.kind != "relationship"]
    relation_records = [record for record in capture.records if record.kind == "relationship"]

    endpoint_uids: dict[str, str] = {}
    for record in object_records:
        raw_payloads[record.raw_payload.sha256] = raw_payload_bytes(record)
        try:
            obj = _normalize_object(
                record,
                scope_id=scope_id,
                source_snapshot_id=source_snapshot_id,
                source_uri=source_uri,
                sanitized_public_fixture=sanitized_public_fixture,
                adapter=adapter,
            )
            objects.append(obj)
            endpoint_uids[record.source_object_id] = obj.uid
            for key in ("standard_id", "id"):
                value = record.payload.get(key)
                if isinstance(value, str) and value:
                    endpoint_uids[value] = obj.uid
        except Exception as exc:
            quarantined.append(
                CtiQuarantinedRecord(
                    record_kind="object",
                    source_record_id=record.source_object_id,
                    reason_code=f"opencti-{type(exc).__name__.casefold()}",
                    reason=str(exc),
                    raw_payload_sha256=record.raw_payload.sha256,
                )
            )

    for record in relation_records:
        raw_payloads[record.raw_payload.sha256] = raw_payload_bytes(record)
        try:
            relations.append(
                _normalize_relation(
                    record,
                    scope_id=scope_id,
                    source_snapshot_id=source_snapshot_id,
                    source_uri=source_uri,
                    sanitized_public_fixture=sanitized_public_fixture,
                    endpoint_uids=endpoint_uids,
                )
            )
        except Exception as exc:
            quarantined.append(
                CtiQuarantinedRecord(
                    record_kind="relation",
                    source_record_id=record.source_object_id,
                    reason_code=f"opencti-{type(exc).__name__.casefold()}",
                    reason=str(exc),
                    raw_payload_sha256=record.raw_payload.sha256,
                )
            )

    batch = CtiNormalizedEvidenceBatch(
        scope_id=scope_id,
        source_snapshot_id=source_snapshot_id,
        objects=tuple(sorted(objects, key=lambda item: item.uid)),
        relations=tuple(sorted(relations, key=lambda item: item.uid)),
        quarantined=tuple(quarantined),
    )
    return NormalizedOpenCTICapture(
        batch=batch,
        raw_payloads=raw_payloads,
        quarantine_counts=batch.quarantine_counts,
        source_snapshot_id=source_snapshot_id,
    )


__all__ = [
    "NORMALIZER_VERSION",
    "NormalizedOpenCTICapture",
    "normalize_complete_capture",
]
