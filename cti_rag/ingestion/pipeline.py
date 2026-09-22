"""Resumable canonical ingestion with staged objects and transactional metadata/outbox."""
from __future__ import annotations
from datetime import datetime,timezone
import json
from cti_rag.contracts import ArtifactType,ComponentFingerprint,NormalizedArtifact,ObservedRevision,RetrievalObservation,SourceObject,namespaced_uid
from cti_rag.ingestion.models import CanonicalBundle,OutboxEvent,QuarantineRecord,RawSnapshotRef

def _now(): return datetime.now(timezone.utc)
def _fingerprint(text):
    parts=text.rsplit("/",1); return ComponentFingerprint(parts[0],parts[1] if len(parts)==2 else "1")

class IngestionPipeline:
    def __init__(self,manifest,connector,normalizer,object_store,metadata_store):
        if connector.source_id != manifest.source_id: raise ValueError("connector source_id does not match manifest")
        self.manifest=manifest; self.connector=connector; self.normalizer=normalizer; self.objects=object_store; self.meta=metadata_store
        self.meta.put_manifest(manifest)
    async def ingest_page(self,cursor=None,failpoint=None):
        page=await self.connector.fetch_page(cursor)
        run_id=namespaced_uid("run","ingestion.batch",{"source":self.manifest.source_id,"cursor":cursor,"next":page.next_cursor,"keys":[r.record_key for r in page.records]})
        started=_now(); self.meta.begin_run(run_id,self.manifest.source_id,started)
        accepted=0; quarantined=0
        try:
            for index,record in enumerate(page.records):
                raw_ref=self.objects.put(record.raw_bytes,self.manifest.retention_class)
                if failpoint=="after_raw_stage" and index==0: raise RuntimeError("failpoint:after_raw_stage")
                if record.claimed_digest and record.claimed_digest != raw_ref.digest:
                    self._quarantine(run_id,record,"checksum_mismatch",raw_ref); quarantined+=1; continue
                try: normalized=self.normalizer.normalize(record)
                except Exception as exc:
                    self._quarantine(run_id,record,f"normalize:{exc}",raw_ref); quarantined+=1; continue
                norm_ref=self.objects.put(normalized.normalized_bytes,self.manifest.retention_class)
                snapshot_uid=namespaced_uid("snap","source.snapshot",{"source":self.manifest.source_id,"record_key":record.record_key,"raw_digest":raw_ref.digest,"upstream_version":record.upstream_version})
                raw_snapshot=RawSnapshotRef(snapshot_uid,self.manifest.source_id,record.record_key,raw_ref,cursor,_now())
                source_object=SourceObject(self.manifest.source_id,normalized.upstream_object_type,normalized.stable_upstream_id,normalized.policy)
                revision=ObservedRevision(source_object.object_uid,raw_ref.digest,normalized.identity_attributes,normalized.temporal,upstream_version=normalized.upstream_version)
                observation_id=namespaced_uid("obs","ingestion.observation",{"source":self.manifest.source_id,"record":record.record_key,"raw":raw_ref.digest,"cursor":cursor})
                observation=RetrievalObservation(observation_id,_now(),ComponentFingerprint("synthetic-or-port-connector","1"),request_fingerprint=str(cursor))
                artifact=NormalizedArtifact(revision.revision_uid,ArtifactType.JSON,norm_ref.digest,ComponentFingerprint("json","1"),_fingerprint(self.normalizer.normalizer_fingerprint),normalized.content_schema_version)
                event_id=namespaced_uid("evt","projection.requested",{"artifact_uid":artifact.artifact_uid})
                outbox=OutboxEvent(event_id,"projection_requested",artifact.artifact_uid,event_id,json.dumps({"artifact_uid":artifact.artifact_uid,"revision_uid":revision.revision_uid},sort_keys=True,separators=(",",":")),"pending",0,_now())
                bundle=CanonicalBundle(self.manifest.source_id,raw_snapshot,source_object,revision,artifact,norm_ref,observation,((source_object.object_uid,revision.revision_uid,"has_revision"),(revision.revision_uid,artifact.artifact_uid,"normalized_as")),outbox)
                self.meta.commit_bundle(bundle); accepted+=1
                if failpoint=="after_metadata_commit" and index==0: raise RuntimeError("failpoint:after_metadata_commit")
            self.meta.advance_checkpoint(self.manifest.source_id,page.next_cursor,run_id,_now()); self.meta.finish_run(run_id,"completed",_now())
            return {"run_id":run_id,"accepted":accepted,"quarantined":quarantined,"next_cursor":page.next_cursor,"exhausted":page.exhausted}
        except Exception:
            self.meta.finish_run(run_id,"failed",_now()); raise
    def _quarantine(self,run_id,record,reason,raw_ref):
        qid=namespaced_uid("q","ingestion.quarantine",{"source":self.manifest.source_id,"record_key":record.record_key,"raw":raw_ref.digest,"reason":reason})
        self.meta.quarantine(QuarantineRecord(qid,run_id,self.manifest.source_id,record.record_key,reason,raw_ref.digest,raw_ref.digest,_now()))
    def orphan_objects(self): return self.objects.orphan_refs(self.meta.referenced_object_digests())
