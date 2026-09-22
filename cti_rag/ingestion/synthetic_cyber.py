"""Tiny deterministic cyber source used to prove ingestion semantics without network access."""
from __future__ import annotations
from datetime import datetime,timezone
import json
from cti_rag.contracts import AccessLabel,AvailabilityBasis,IdentityAttribute,PolicyLabels,ProcessingClass,TemporalMetadata,canonical_json_bytes
from cti_rag.ingestion.models import SourceManifest
from cti_rag.ports.capabilities import BackendCapabilities
from cti_rag.ports.normalizer import NormalizedRecord
from cti_rag.ports.source import SourcePage,SourceRecord

SYNTHETIC_MANIFEST=SourceManifest(
    source_id="synthetic-cyber",domain="cybersecurity",format="json",upstream_object_type="cve",
    versioning_strategy="content_digest+upstream_version",license_id="fixture-public",
    access_label=AccessLabel.PUBLIC,processing_class=ProcessingClass.LOCAL_ONLY,retention_class="standard",
    update_strategy="cursor",deletion_strategy="explicit_revocation",availability_basis=AvailabilityBasis.SOURCE_PUBLISHED,
    supported_projections=("exact","lexical","dense"),
)

class SyntheticCyberConnector:
    source_id="synthetic-cyber"
    capabilities=BackendCapabilities(pagination=True,cancellation=True,max_batch_size=16)
    def __init__(self,records=None,page_size=2):
        self.records=tuple(records or (
            SourceRecord("CVE-2026-0001",b'{"id":"CVE-2026-0001","summary":"synthetic buffer boundary issue","published_at":"2026-01-01T00:00:00Z"}',"1"),
            SourceRecord("CVE-2026-0002",b'{"id":"CVE-2026-0002","summary":"synthetic auth state issue","published_at":"2026-01-02T00:00:00Z"}',"1"),
        )); self.page_size=page_size
    async def fetch_page(self,cursor=None,deadline=None,cancellation_token=None):
        start=int(cursor or 0); end=min(len(self.records),start+self.page_size); next_cursor=None if end>=len(self.records) else str(end)
        return SourcePage(self.records[start:end],next_cursor,exhausted=end>=len(self.records))

class SyntheticCyberNormalizer:
    normalizer_fingerprint="synthetic-cyber-normalizer/1"
    def normalize(self,record:SourceRecord):
        try:data=json.loads(record.raw_bytes.decode("utf-8"))
        except Exception as exc: raise ValueError("invalid_json") from exc
        cve=str(data.get("id","")).upper(); summary=data.get("summary")
        if not cve.startswith("CVE-") or not isinstance(summary,str) or not summary.strip(): raise ValueError("invalid_synthetic_cyber_record")
        published=str(data.get("published_at","")); dt=datetime.fromisoformat(published.replace("Z","+00:00")).astimezone(timezone.utc)
        normalized={"id":cve,"summary":summary.strip(),"published_at":dt.isoformat().replace("+00:00","Z")}
        temporal=TemporalMetadata(first_observed_at=dt,recorded_from=dt,published_at=dt,available_at=dt,available_at_basis=AvailabilityBasis.SOURCE_PUBLISHED)
        return NormalizedRecord(
            stable_upstream_id=cve,upstream_object_type="cve",normalized_bytes=canonical_json_bytes(normalized),
            identity_attributes=(IdentityAttribute("cve_id",cve),),temporal=temporal,
            policy=PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY,license_id="fixture-public",retention_class="standard"),
            content_schema_version="synthetic-cve/1",upstream_version=record.upstream_version,
        )
