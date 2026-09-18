"""OpenCTI complete-inventory reconciliation into live visibility overlays."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from packages.evidence.ids import canonical_hash
from packages.evidence.lifecycle import InventoryOutcome, LifecycleAuthority

from .checkpoint import CheckpointKey
from .reader import CAPTURE_KINDS, CompleteCapture


@dataclass(frozen=True)
class ReconciliationResult:
    complete: bool
    inventory_run_ids: tuple[str, ...]
    tombstones_written: int
    lease_expires_at: tuple[str, ...]
    missing_classification: str


def _current_revisions(batch, source_instance: str):
    result: dict[str, set[tuple[str, str, str]]] = {}
    for obj in batch.objects:
        for ref in obj.source_refs:
            if ref.source_instance == source_instance:
                result.setdefault(ref.source_object_id, set()).add(
                    ("object", obj.uid, obj.revision_uid)
                )
    for relation in batch.relations:
        for ref in relation.evidence_refs:
            if ref.source_instance == source_instance:
                result.setdefault(ref.source_object_id, set()).add(
                    ("relation", relation.uid, relation.revision_uid)
                )
    return result


def _explicit_status(capture: CompleteCapture) -> dict[str, str]:
    status: dict[str, str] = {}
    for record in capture.records:
        payload = record.payload
        if payload.get("deleted") is True or payload.get("x_opencti_deleted") is True:
            status[record.source_object_id] = "upstream_deleted"
        elif payload.get("revoked") is True:
            status[record.source_object_id] = "revoked"
    return status


def type_fingerprint(kind: str) -> str:
    if kind not in CAPTURE_KINDS:
        raise ValueError(f"unsupported OpenCTI reconciliation type: {kind}")
    return canonical_hash(["opencti-inventory-type-v1", kind])


def reconcile_complete_capture(
    authority: LifecycleAuthority,
    *,
    capture: CompleteCapture,
    batch,
    checkpoint_keys: tuple[CheckpointKey, ...],
    max_staleness_seconds: int,
    authorized: bool = True,
) -> ReconciliationResult:
    if not capture.complete:
        raise ValueError("only a complete capture may reconcile visibility")
    if max_staleness_seconds <= 0:
        raise ValueError("reconciliation requires an explicit staleness budget")
    by_kind: dict[str, list[Any]] = {kind: [] for kind in CAPTURE_KINDS}
    for record in capture.records:
        if record.kind not in by_kind:
            raise ValueError(f"unsupported captured type: {record.kind}")
        by_kind[record.kind].append(record)
    pages_by_kind = {
        kind: sum(1 for page in capture.pages if page.kind == kind)
        for kind in CAPTURE_KINDS
    }
    current = _current_revisions(batch, capture.source_instance)
    explicit = _explicit_status(capture)
    outcomes: list[InventoryOutcome] = []
    key_map = {key.supported_type: key for key in checkpoint_keys}

    for kind in CAPTURE_KINDS:
        key = key_map[kind]
        seen = tuple(
            sorted(record.source_object_id for record in by_kind[kind])
        )
        current_for_kind = {
            source_id: values
            for source_id, values in current.items()
            if source_id in set(seen)
        }
        outcomes.append(
            authority.record_inventory(
                domain=key.domain,
                scope_id=key.scope_id,
                source_instance=key.source_instance,
                supported_type=kind,
                type_fingerprint=type_fingerprint(kind),
                filter_fingerprint=key.filter_fingerprint,
                seen_source_ids=seen,
                current_revisions=current_for_kind,
                explicit_status={
                    source_id: reason
                    for source_id, reason in explicit.items()
                    if source_id in set(seen)
                },
                complete=True,
                authorized=authorized,
                page_count=pages_by_kind[kind],
                capture_started_at=capture.capture_started_at,
                capture_completed_at=capture.capture_completed_at,
                max_staleness_seconds=max_staleness_seconds,
            )
        )
    return ReconciliationResult(
        complete=all(item.complete for item in outcomes),
        inventory_run_ids=tuple(item.run_id for item in outcomes),
        tombstones_written=sum(item.tombstones_written for item in outcomes),
        lease_expires_at=tuple(
            item.lease_expires_at
            for item in outcomes
            if item.lease_expires_at is not None
        ),
        missing_classification="no_longer_visible",
    )


def record_failed_reconciliation(
    authority: LifecycleAuthority,
    *,
    checkpoint_keys: tuple[CheckpointKey, ...],
    source_instance: str,
    reason: str,
    max_staleness_seconds: int,
    authorized: bool,
) -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for key in checkpoint_keys:
        authority.record_inventory_failure(
            domain=key.domain,
            scope_id=key.scope_id,
            source_instance=source_instance,
            supported_type=key.supported_type,
            type_fingerprint=type_fingerprint(key.supported_type),
            filter_fingerprint=key.filter_fingerprint,
            failure_reason=reason,
            capture_started_at=now,
            capture_completed_at=now,
            max_staleness_seconds=max_staleness_seconds,
            authorized=authorized,
        )


__all__ = [
    "ReconciliationResult",
    "record_failed_reconciliation",
    "reconcile_complete_capture",
    "type_fingerprint",
]
