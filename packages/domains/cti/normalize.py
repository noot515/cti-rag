"""Deterministic CTI fixture/source normalization into generic evidence contracts."""

from __future__ import annotations

from typing import Any, Mapping

from packages.evidence.ids import object_uid, relation_revision_uid, relation_uid, revision_uid
from packages.evidence.provenance import raw_payload_sha256
from packages.evidence.schema import LifecycleState, Qualifier, SourceRef

from .identifiers import normalize_identifier
from .markings import CtiMarking, GranularMarking, to_policy_metadata
from .relations import normalize_relation
from .schema import (
    CtiAttackPatternData,
    CtiNormalizedEvidenceBatch,
    CtiObject,
    CtiOtherData,
    CtiRelationship,
    CtiReportData,
    CtiVulnerabilityData,
    CtiWeaknessData,
)
from .validation import require_synthetic_fixture

NORMALIZER_VERSION = "cti-normalizer-v1"


def _source_ref(
    *,
    domain: str,
    source_instance: str,
    source_object_id: str,
    source_snapshot_id: str,
    payload: Mapping[str, Any],
    upstream_origin: str,
    source_uri: str | None,
) -> SourceRef:
    return SourceRef(
        domain=domain,
        source_instance=source_instance,
        source_object_id=source_object_id,
        upstream_origin=upstream_origin,
        source_uri=source_uri,
        raw_payload_sha256=raw_payload_sha256(payload),
        source_snapshot_id=source_snapshot_id,
        normalizer_version=NORMALIZER_VERSION,
    )


def _parse_markings(record: Mapping[str, Any]) -> tuple[tuple[CtiMarking, ...], tuple[GranularMarking, ...]]:
    markings = tuple(CtiMarking.model_validate(item) for item in record.get("markings", []))
    granular = tuple(
        GranularMarking.model_validate(item) for item in record.get("granular_markings", [])
    )
    return markings, granular


def _family_data(record: Mapping[str, Any]):
    object_type = str(record["object_type"])
    data = record.get("family_data") or {}
    if object_type == "vulnerability":
        return CtiVulnerabilityData.model_validate({"family": "vulnerability", **data})
    if object_type == "weakness":
        return CtiWeaknessData.model_validate({"family": "weakness", **data})
    if object_type in {"attack-pattern", "technique"}:
        return CtiAttackPatternData.model_validate({"family": "attack_pattern", **data})
    if object_type == "report":
        return CtiReportData.model_validate({"family": "report", **data})
    return CtiOtherData(family="other", source_type=object_type)


def normalize_cti_fixture_manifest(manifest: Mapping[str, Any]) -> CtiNormalizedEvidenceBatch:
    if manifest.get("schema_version") != "cti-fixture-v1":
        raise ValueError("unsupported CTI fixture schema_version")
    require_synthetic_fixture(bool(manifest.get("synthetic")))
    domain = "cti"
    source_instance = str(manifest["source_instance"])
    scope_id = str(manifest["scope_id"])
    source_snapshot_id = str(manifest["source_snapshot_id"])
    upstream_origin = str(manifest.get("upstream_origin", "synthetic-fixture"))
    source_uri = manifest.get("source_uri")

    objects: list[CtiObject] = []
    by_source_id: dict[str, CtiObject] = {}
    for record in manifest.get("objects", []):
        source_object_id = str(record["source_object_id"])
        uid = object_uid(domain, source_instance, source_object_id)
        rev = revision_uid(uid, record)
        markings, granular = _parse_markings(record)
        source_ref = _source_ref(
            domain=domain,
            source_instance=source_instance,
            source_object_id=source_object_id,
            source_snapshot_id=source_snapshot_id,
            payload=record,
            upstream_origin=upstream_origin,
            source_uri=source_uri,
        )
        external_ids = tuple(
            normalize_identifier(str(item["namespace"]), str(item["value"]))
            for item in record.get("external_ids", [])
        )
        policy = to_policy_metadata(
            source_instances=(source_instance,),
            markings=markings,
            granular_markings=granular,
            declared_marking_refs=tuple(record.get("marking_refs", [])),
        )
        if record.get("deleted"):
            lifecycle = LifecycleState.DELETED
        elif record.get("revoked"):
            lifecycle = LifecycleState.REVOKED
        elif record.get("deprecated"):
            lifecycle = LifecycleState.DEPRECATED
        else:
            lifecycle = LifecycleState.ACTIVE
        obj = CtiObject(
            uid=uid,
            revision_uid=rev,
            scope_id=scope_id,
            object_type=str(record["object_type"]),
            name=record.get("name"),
            description=record.get("description"),
            external_ids=external_ids,
            aliases=tuple(record.get("aliases", [])),
            source_refs=(source_ref,),
            created_at=record.get("created_at"),
            modified_at=record.get("modified_at"),
            observed_at=record.get("observed_at"),
            raw_payload_ref=f"sha256:{source_ref.raw_payload_sha256}",
            lifecycle_state=lifecycle,
            policy=policy,
            stix_type=record.get("stix_type"),
            stix_id=record.get("stix_id"),
            revoked=bool(record.get("revoked", False)),
            deprecated=bool(record.get("deprecated", False)),
            deleted=bool(record.get("deleted", False)),
            confidence=record.get("confidence"),
            marking_refs=tuple(record.get("marking_refs", [])),
            markings=markings,
            granular_markings=granular,
            family_data=_family_data(record),
        )
        objects.append(obj)
        by_source_id[source_object_id] = obj

    relations: list[CtiRelationship] = []
    for record in manifest.get("relations", []):
        source_record_id = str(record["source_record_id"])
        source_object = by_source_id[str(record["source_object_id"])]
        target_object = by_source_id[str(record["target_object_id"])]
        normalized = normalize_relation(str(record["normalized_relation"]))
        qualifiers = tuple(
            Qualifier(name=str(item["name"]), value=item.get("value"))
            for item in record.get("qualifiers", [])
        )
        uid = relation_uid(
            domain=domain,
            source_instance=source_instance,
            source_record_id=source_record_id,
            source_object_uid=source_object.uid,
            target_object_uid=target_object.uid,
            normalized_relation=normalized,
            source_field_path=record.get("source_field_path"),
            qualifiers=[qualifier.model_dump(mode="json") for qualifier in qualifiers],
            upstream_relation_id=record.get("upstream_relation_id"),
        )
        rev = relation_revision_uid(uid, record)
        markings, granular = _parse_markings(record)
        source_ref = _source_ref(
            domain=domain,
            source_instance=source_instance,
            source_object_id=source_record_id,
            source_snapshot_id=source_snapshot_id,
            payload=record,
            upstream_origin=upstream_origin,
            source_uri=source_uri,
        )
        policy = to_policy_metadata(
            source_instances=(source_instance,),
            markings=markings,
            granular_markings=granular,
            declared_marking_refs=tuple(record.get("marking_refs", [])),
        )
        relation = CtiRelationship(
            uid=uid,
            revision_uid=rev,
            scope_id=scope_id,
            source_object_uid=source_object.uid,
            target_object_uid=target_object.uid,
            original_relation=str(record.get("original_relation", normalized)),
            normalized_relation=normalized,
            direction=str(record.get("direction", "forward")),
            assertion_kind=str(record.get("assertion_kind", "catalog_mapping")),
            evidence_refs=(source_ref,),
            qualifiers=qualifiers,
            source_field_path=record.get("source_field_path"),
            applicability=tuple(
                Qualifier(name=str(item["name"]), value=item.get("value"))
                for item in record.get("applicability", [])
            ),
            policy=policy,
            relationship_kind=str(record.get("relationship_kind", "mapping")),
            source_evidence_locator=record.get("source_field_path"),
            marking_refs=tuple(record.get("marking_refs", [])),
            markings=markings,
            granular_markings=granular,
            producer_confidence=record.get("confidence"),
        )
        relations.append(relation)

    # STIX/report object_refs are source references, not causal assertions. Convert
    # them to independently citable `references` evidence with exact field paths.
    target_by_reference: dict[str, CtiObject] = dict(by_source_id)
    for obj in objects:
        if obj.stix_id:
            target_by_reference[obj.stix_id] = obj
    for report in objects:
        family = report.family_data
        if not isinstance(family, CtiReportData):
            continue
        report_source_id = report.source_refs[0].source_object_id
        for index, referenced_id in enumerate(family.object_refs):
            target = target_by_reference.get(referenced_id)
            if target is None:
                continue
            field_path = f"object_refs[{index}]"
            relation_record = {
                "source_record_id": report_source_id,
                "source_object_id": report_source_id,
                "target_object_id": referenced_id,
                "original_relation": "object_refs",
                "normalized_relation": "references",
                "assertion_kind": "embedded_reference",
                "source_field_path": field_path,
            }
            uid = relation_uid(
                domain=domain,
                source_instance=source_instance,
                source_record_id=report_source_id,
                source_object_uid=report.uid,
                target_object_uid=target.uid,
                normalized_relation="references",
                source_field_path=field_path,
            )
            rev = relation_revision_uid(uid, relation_record)
            source_ref = _source_ref(
                domain=domain,
                source_instance=source_instance,
                source_object_id=report_source_id,
                source_snapshot_id=source_snapshot_id,
                payload=relation_record,
                upstream_origin=upstream_origin,
                source_uri=source_uri,
            )
            relations.append(
                CtiRelationship(
                    uid=uid,
                    revision_uid=rev,
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
        domain=domain,
        scope_id=scope_id,
        source_snapshot_id=source_snapshot_id,
        objects=tuple(objects),
        relations=tuple(relations),
    )
