"""Canonical ingestion control-plane records."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
from typing import Optional,Tuple
from cti_rag.contracts import AccessLabel,AvailabilityBasis,ProcessingClass

def utc_now(): return datetime.now(timezone.utc)
@dataclass(frozen=True)
class SourceManifest:
    source_id:str; domain:str; format:str; upstream_object_type:str; versioning_strategy:str; license_id:Optional[str]
    access_label:AccessLabel; processing_class:ProcessingClass; retention_class:str; update_strategy:str; deletion_strategy:str
    availability_basis:AvailabilityBasis; supported_projections:Tuple[str,...]; schema_version:str="source-manifest/1"
    def __post_init__(self):
        required=(self.source_id,self.domain,self.format,self.upstream_object_type,self.versioning_strategy,self.retention_class,self.update_strategy,self.deletion_strategy)
        if not all(v.strip() for v in required): raise ValueError("source manifest required fields must be non-empty")
        if not self.supported_projections: raise ValueError("source manifest requires at least one supported projection")
@dataclass(frozen=True)
class ObjectRef:
    digest:str; size_bytes:int; retention_class:str; relative_path:str
@dataclass(frozen=True)
class RawSnapshotRef:
    snapshot_uid:str; source_id:str; record_key:str; object_ref:ObjectRef; upstream_cursor:Optional[str]; created_at:datetime
@dataclass(frozen=True)
class IngestionRun:
    run_id:str; source_id:str; status:str; started_at:datetime; finished_at:Optional[datetime]=None
@dataclass(frozen=True)
class IngestionCheckpoint:
    source_id:str; cursor:Optional[str]; committed_run_id:str; updated_at:datetime
@dataclass(frozen=True)
class QuarantineRecord:
    quarantine_id:str; run_id:str; source_id:str; record_key:str; reason:str; raw_digest:Optional[str]; object_digest:Optional[str]; created_at:datetime
@dataclass(frozen=True)
class OutboxEvent:
    event_id:str; kind:str; aggregate_id:str; idempotency_key:str; payload_json:str; status:str; attempts:int; available_at:datetime; last_error:Optional[str]=None
@dataclass(frozen=True)
class CanonicalBundle:
    source_id:str; raw_snapshot:RawSnapshotRef; source_object:object; revision:object; artifact:object; normalized_ref:ObjectRef; observation:object; dependencies:Tuple[Tuple[str,str,str],...]; outbox:OutboxEvent
