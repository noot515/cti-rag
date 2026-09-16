"""Deterministic, fail-closed CTI normalization into generic evidence contracts."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from packages.evidence.ids import object_uid, relation_revision_uid, relation_uid, revision_uid
from packages.evidence.provenance import canonical_revision_projection, raw_payload_sha256
from packages.evidence.schema import LifecycleState, Qualifier, SourceRef

from .identifiers import normalize_identifier
from .markings import CtiMarking, GranularMarking, to_policy_metadata, unsupported_granular_selectors
from .relations import normalize_assertion_kind, normalize_relation
from .schema import (
    CtiAttackPatternData,
    CtiIndicatorData,
    CtiNormalizedEvidenceBatch,
    CtiObject,
    CtiOtherData,
    CtiQuarantinedRecord,
    CtiRelationship,
    CtiReportData,
    CtiVulnerabilityData,
    CtiWeaknessData,
)
from .validation import require_synthetic_fixture

NORMALIZER_VERSION = "cti-normalizer-v2"
_CAPTURE_ONLY_FIELDS = frozenset({"captured_at", "polled_at", "retrieved_at", "source_snapshot_id"})
_POLICY_FIELDS = frozenset({"marking_refs", "markings", "granular_markings"})
_SUPPORTED_OBJECT_TYPES = frozenset(
    {"vulnerability", "weakness", "attack-pattern", "technique", "report", "indicator", "source-specific"}
)


class CtiNormalizationError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _source_ref(
    *,
    source_instance: str,
    source_object_id: str,
    source_snapshot_id: str,
    payload: Mapping[str, Any],
    upstream_origin: str,
    source_uri: str | None,
) -> SourceRef:
    return SourceRef(
        domain="cti",
        source_instance=source_instance,
        source_object_id=source_object_id,
        upstream_origin=upstream_origin,
        source_uri=source_uri,
        raw_payload_sha256=raw_payload_sha256(payload),
        source_snapshot_id=source_snapshot_id,
        normalizer_version=NORMALIZER_VERSION,
    )


def _definition_map(manifest: Mapping[str, Any]) -> dict[str, CtiMarking]:
    definitions: dict[str, CtiMarking] = {}
    for item in manifest.get("marking_definitions", []):
        marking = CtiMarking.model_validate(item)
        if marking.marking_ref in definitions and definitions[marking.marking_ref] != marking:
            raise ValueError(f"conflicting marking definition: {marking.marking_ref}")
        definitions[marking.marking_ref] = marking
    return definitions


def _parse_markings(
    record: Mapping[str, Any], definitions: Mapping[str, CtiMarking]
) -> tuple[tuple[CtiMarking, ...], tuple[GranularMarking, ...], tuple[str, ...]]:
    inline = {mark.marking_ref: mark for mark in (CtiMarking.model_validate(item) for item in record.get("markings", []))}
    granular = tuple(GranularMarking.model_validate(item) for item in record.get("granular_markings", []))
    declared = tuple(dict.fromkeys((*record.get("marking_refs", []), *(item.marking_ref for item in granular))))
    resolved: list[CtiMarking] = []
    for ref in declared:
        if ref in inline:
            resolved.append(inline[ref])
        elif ref in definitions:
            resolved.append(definitions[ref])
    for ref, marking in inline.items():
        if ref not in declared:
            resolved.append(marking)
    return tuple(dict.fromkeys(resolved)), granular, declared


def _policy_for(
    record: Mapping[str, Any],
    *,
    source_instance: str,
    definitions: Mapping[str, CtiMarking],
    unmarked_data_public: bool,
):
    markings, granular, declared = _parse_markings(record, definitions)
    unsupported = unsupported_granular_selectors(granular)
    if unsupported:
        raise CtiNormalizationError(
            "unsupported-granular-selector", f"unsupported granular selector: {unsupported[0]}"
        )
    if not markings and not declared and not granular and not unmarked_data_public:
        raise CtiNormalizationError(
            "unmarked-source-not-public", "unmarked CTI is public only under an explicit source contract"
        )
    policy = to_policy_metadata(
        source_instances=(source_instance,),
        markings=markings,
        granular_markings=granular,
        declared_marking_refs=declared,
    )
    if policy.unresolved_markings:
        raise CtiNormalizationError(
            "unresolved-marking", "marking reference or definition is unresolved/unsupported"
        )
    return markings, granular, declared, policy


def _family_data(record: Mapping[str, Any]):
    object_type = str(record.get("object_type", ""))
    data = record.get("family_data") or {}
    if object_type not in _SUPPORTED_OBJECT_TYPES:
        raise CtiNormalizationError(
            "unsupported-object-family", f"unsupported CTI object family: {object_type or '<missing>'}"
        )
    if object_type == "vulnerability":
        return CtiVulnerabilityData.model_validate({"family": "vulnerability", **data})
    if object_type == "weakness":
        return CtiWeaknessData.model_validate({"family": "weakness", **data})
    if object_type in {"attack-pattern", "technique"}:
        return CtiAttackPatternData.model_validate({"family": "attack_pattern", **data})
    if object_type == "report":
        return CtiReportData.model_validate({"family": "report", **data})
    if object_type == "indicator":
        return CtiIndicatorData.model_validate({"family": "indicator", **data})
    source_type = data.get("source_type")
    if not source_type:
        raise CtiNormalizationError(
            "unsupported-object-family", "source-specific object requires family_data.source_type"
        )
    return CtiOtherData(family="other", source_type=str(source_type))


def _lifecycle(record: Mapping[str, Any]) -> LifecycleState:
    if record.get("deleted"):
        return LifecycleState.DELETED
    if record.get("revoked"):
        return LifecycleState.REVOKED
    if record.get("deprecated"):
        return LifecycleState.DEPRECATED
    return LifecycleState.ACTIVE


def _revision_projection(
    *,
    source_instance: str,
    source_object_id: str,
    upstream_origin: str,
    source_uri: str | None,
    record: Mapping[str, Any],
    policy: Any,
    evidence_locators: tuple[str, ...] = (),
) -> dict[str, Any]:
    semantic = {
        key: value
        for key, value in record.items()
        if key not in _CAPTURE_ONLY_FIELDS and key not in _POLICY_FIELDS and key != "schema_version"
    }
    return canonical_revision_projection(
        source_instance=source_instance,
        source_object_id=source_object_id,
        upstream_origin=upstream_origin,
        source_uri=source_uri,
        normalizer_version=NORMALIZER_VERSION,
        semantic_fields=semantic,
        policy_fields=policy.model_dump(mode="json"),
        evidence_locators=evidence_locators,
    )


def _quarantine(
    kind: str,
    record: Mapping[str, Any],
    reason_code: str,
    reason: str,
    source_id: str | None = None,
) -> CtiQuarantinedRecord:
    return CtiQuarantinedRecord(
        record_kind=kind,
        source_record_id=source_id
        or str(record.get("source_object_id") or record.get("source_record_id") or "")
        or None,
        reason_code=reason_code,
        reason=reason,
        raw_payload_sha256=raw_payload_sha256(record),
    )


def normalize_cti_fixture_manifest(manifest: Mapping[str, Any]) -> CtiNormalizedEvidenceBatch:
    if manifest.get("schema_version") not in {"cti-fixture-v1", "cti-corpus-manifest-v1"}:
        raise ValueError("unsupported CTI fixture schema_version")
    require_synthetic_fixture(bool(manifest.get("synthetic")))
    source_instance = str(manifest["source_instance"])
    scope_id = str(manifest["scope_id"])
    source_snapshot_id = str(manifest["source_snapshot_id"])
    upstream_origin = str(manifest.get("upstream_origin", "synthetic-fixture"))
    source_uri = manifest.get("source_uri")
    unmarked_data_public = manifest.get("unmarked_data_public") is True
    definitions = _definition_map(manifest)

    objects: list[CtiObject] = []
    quarantined: list[CtiQuarantinedRecord] = []
    by_source_id: dict[str, CtiObject] = {}
    by_reference: dict[str, CtiObject] = {}

    for record in manifest.get("objects", []):
        try:
            source_object_id = str(record["source_object_id"])
            object_type = str(record["object_type"])
            markings, granular, declared, policy = _policy_for(
                record,
                source_instance=source_instance,
                definitions=definitions,
                unmarked_data_public=unmarked_data_public,
            )
            uid = object_uid("cti", source_instance, source_object_id)
            external_ids = tuple(
                normalize_identifier(str(item["namespace"]), str(item["value"]))
                for item in record.get("external_ids", [])
            )
            source_ref = _source_ref(
                source_instance=source_instance,
                source_object_id=source_object_id,
                source_snapshot_id=source_snapshot_id,
                payload=record,
                upstream_origin=upstream_origin,
                source_uri=source_uri,
            )
            projection = _revision_projection(
                source_instance=source_instance,
                source_object_id=source_object_id,
                upstream_origin=upstream_origin,
                source_uri=source_uri,
                record=record,
                policy=policy,
            )
            obj = CtiObject(
                uid=uid,
                revision_uid=revision_uid(uid, projection),
                scope_id=scope_id,
                object_type=object_type,
                name=record.get("name"),
                description=record.get("description"),
                external_ids=external_ids,
                aliases=tuple(record.get("aliases", [])),
                source_refs=(source_ref,),
                created_at=record.get("created_at"),
                modified_at=record.get("modified_at"),
                observed_at=record.get("observed_at"),
                raw_payload_ref=f"sha256:{source_ref.raw_payload_sha256}",
                lifecycle_state=_lifecycle(record),
                policy=policy,
                stix_family=record.get("stix_family"),
                stix_type=record.get("stix_type"),
                stix_id=record.get("stix_id"),
                revoked=bool(record.get("revoked", False)),
                deprecated=bool(record.get("deprecated", False)),
                deleted=bool(record.get("deleted", False)),
                confidence=record.get("confidence"),
                marking_refs=declared,
                markings=markings,
                granular_markings=granular,
                family_data=_family_data(record),
            )
            objects.append(obj)
            by_source_id[source_object_id] = obj
            by_reference[source_object_id] = obj
            if obj.stix_id:
                by_reference[obj.stix_id] = obj
        except CtiNormalizationError as exc:
            quarantined.append(_quarantine("object", record, exc.reason_code, str(exc)))
        except Exception as exc:
            quarantined.append(_quarantine("object", record, "malformed-object", str(exc)))

    relations: list[CtiRelationship] = []
    for record in manifest.get("relations", []):
        try:
            source_record_id = str(record["source_record_id"])
            source_obj = by_source_id.get(str(record["source_object_id"]))
            target_obj = by_source_id.get(str(record["target_object_id"]))
            if source_obj is None or target_obj is None:
                raise CtiNormalizationError(
                    "dangling-relation-endpoint", "relation endpoint is missing or suppressed"
                )
            normalized = normalize_relation(str(record["normalized_relation"]))
            assertion_kind = normalize_assertion_kind(str(record.get("assertion_kind", "explicit")))
            markings, granular, declared, policy = _policy_for(
                record,
                source_instance=source_instance,
                definitions=definitions,
                unmarked_data_public=unmarked_data_public,
            )
            qualifiers = tuple(
                Qualifier(name=str(item["name"]), value=item.get("value"))
                for item in record.get("qualifiers", [])
            )
            field_path = record.get("source_field_path")
            uid = relation_uid(
                domain="cti",
                source_instance=source_instance,
                source_record_id=source_record_id,
                source_object_uid=source_obj.uid,
                target_object_uid=target_obj.uid,
                normalized_relation=normalized,
                source_field_path=field_path,
                qualifiers=[item.model_dump(mode="json") for item in qualifiers],
                upstream_relation_id=record.get("upstream_relation_id"),
            )
            source_ref = _source_ref(
                source_instance=source_instance,
                source_object_id=source_record_id,
                source_snapshot_id=source_snapshot_id,
                payload=record,
                upstream_origin=upstream_origin,
                source_uri=source_uri,
            )
            projection = _revision_projection(
                source_instance=source_instance,
                source_object_id=source_record_id,
                upstream_origin=upstream_origin,
                source_uri=source_uri,
                record=record,
                policy=policy,
                evidence_locators=(field_path,) if field_path else (),
            )
            relations.append(
                CtiRelationship(
                    uid=uid,
                    revision_uid=relation_revision_uid(uid, projection),
                    scope_id=scope_id,
                    source_object_uid=source_obj.uid,
                    target_object_uid=target_obj.uid,
                    original_relation=str(record.get("original_relation", normalized)),
                    normalized_relation=normalized,
                    direction=str(record.get("direction", "forward")),
                    assertion_kind=assertion_kind,
                    evidence_refs=(source_ref,),
                    qualifiers=qualifiers,
                    source_field_path=field_path,
                    applicability=tuple(
                        Qualifier(name=str(item["name"]), value=item.get("value"))
                        for item in record.get("applicability", [])
                    ),
                    policy=policy,
                    relationship_kind=str(record.get("relationship_kind", "mapping")),
                    source_evidence_locator=field_path,
                    marking_refs=declared,
                    markings=markings,
                    granular_markings=granular,
                    producer_confidence=record.get("confidence"),
                )
            )
        except CtiNormalizationError as exc:
            quarantined.append(_quarantine("relation", record, exc.reason_code, str(exc)))
        except Exception as exc:
            quarantined.append(_quarantine("relation", record, "malformed-relation", str(exc)))

    for report in objects:
        if not isinstance(report.family_data, CtiReportData):
            continue
        report_source_id = report.source_refs[0].source_object_id
        for index, ref_id in enumerate(report.family_data.object_refs):
            target = by_reference.get(ref_id)
            if target is None:
                raw = {
                    "source_record_id": report_source_id,
                    "referenced_id": ref_id,
                    "source_field_path": f"object_refs[{index}]",
                }
                quarantined.append(
                    _quarantine(
                        "reference",
                        raw,
                        "unresolved-object-reference",
                        f"report object_ref cannot be resolved: {ref_id}",
                        report_source_id,
                    )
                )
                continue
            field_path = f"object_refs[{index}]"
            relation_record = {
                "source_record_id": report_source_id,
                "source_object_id": report_source_id,
                "target_object_id": ref_id,
                "original_relation": "object_refs",
                "normalized_relation": "references",
                "assertion_kind": "embedded_reference",
                "source_field_path": field_path,
            }
            uid = relation_uid(
                domain="cti",
                source_instance=source_instance,
                source_record_id=report_source_id,
                source_object_uid=report.uid,
                target_object_uid=target.uid,
                normalized_relation="references",
                source_field_path=field_path,
            )
            source_ref = _source_ref(
                source_instance=source_instance,
                source_object_id=report_source_id,
                source_snapshot_id=source_snapshot_id,
                payload=relation_record,
                upstream_origin=upstream_origin,
                source_uri=source_uri,
            )
            projection = _revision_projection(
                source_instance=source_instance,
                source_object_id=report_source_id,
                upstream_origin=upstream_origin,
                source_uri=source_uri,
                record=relation_record,
                policy=report.policy,
                evidence_locators=(field_path,),
            )
            relations.append(
                CtiRelationship(
                    uid=uid,
                    revision_uid=relation_revision_uid(uid, projection),
                    scope_id=scope_id,
                    source_object_uid=report.uid,
                    target_object_uid=target.uid,
                    original_relation="object_refs",
                    normalized_relation="references",
                    direction="forward",
                    assertion_kind="embedded_reference",
                    evidence_refs=(source_ref,),
                    source_field_path=field_path,
                    policy=report.policy,
                    relationship_kind="reference",
                    source_evidence_locator=field_path,
                    marking_refs=report.marking_refs,
                    markings=report.markings,
                    granular_markings=report.granular_markings,
                    producer_confidence=report.confidence,
                )
            )

    return CtiNormalizedEvidenceBatch(
        domain="cti",
        scope_id=scope_id,
        source_snapshot_id=source_snapshot_id,
        objects=tuple(objects),
        relations=tuple(relations),
        quarantined=tuple(quarantined),
    )


def load_cti_corpus_fixture(manifest_path: Path) -> CtiNormalizedEvidenceBatch:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "cti-corpus-manifest-v1":
        raise ValueError("unsupported CTI corpus manifest schema_version")
    relative = str(payload["objects_file"])
    if "\\" in relative:
        raise ValueError("objects_file must use POSIX separators")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or "." in posix.parts:
        raise ValueError("objects_file must be a normalized relative path")
    path = (manifest_path.parent / relative).resolve()
    root = manifest_path.parent.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("objects_file escapes fixture root") from exc
    raw = path.read_bytes()
    observed = sha256(raw).hexdigest()
    if observed != payload["objects_sha256"]:
        raise ValueError(
            f"objects.jsonl hash mismatch: expected {payload['objects_sha256']}, observed {observed}"
        )
    objects: list[dict[str, Any]] = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("schema_version") != "cti-object-record-v1":
            raise ValueError("unsupported CTI object record schema_version")
        objects.append({key: value for key, value in record.items() if key != "schema_version"})
    merged = {key: value for key, value in payload.items() if key not in {"objects_file", "objects_sha256"}}
    merged["objects"] = objects
    return normalize_cti_fixture_manifest(merged)
