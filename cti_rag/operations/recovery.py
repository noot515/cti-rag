"""Backup, restore, rebuild, rollback, tombstone propagation, and health orchestration."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,json,shutil
from pathlib import Path

@dataclass(frozen=True)
class OperationalPaths:
    root:Path
    @classmethod
    def from_root(cls,root):
        root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True);return cls(root)
    @property
    def objects(self):return self.root/"objects"
    @property
    def canonical_db(self):return self.root/"canonical.sqlite"
    @property
    def catalog_db(self):return self.root/"catalog.sqlite"
    @property
    def cache_root(self):return self.root/"cache"

class RecoveryError(RuntimeError):pass

def _sha(data):return hashlib.sha256(data).hexdigest()

class RecoveryManager:
    def __init__(self,object_store,metadata_store,catalog,publisher):
        self.objects=object_store;self.metadata=metadata_store;self.catalog=catalog;self.publisher=publisher
    def create_backup(self,destination):
        destination=Path(destination).resolve()
        if destination.exists() and any(destination.iterdir()):raise RecoveryError("backup destination must be empty")
        destination.mkdir(parents=True,exist_ok=True);(destination/"objects").mkdir()
        object_rows=[]
        for ref in self.objects.iter_refs():
            data=self.objects.get(ref);target=destination/"objects"/ref.relative_key;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            object_rows.append({"digest":ref.digest,"size_bytes":ref.size_bytes,"retention_class":ref.retention_class,"relative_key":ref.relative_key})
        metadata=self.metadata.backup_json();catalog=self.catalog.backup_json()
        (destination/"canonical-metadata.json").write_text(metadata,encoding="utf-8");(destination/"snapshot-catalog.json").write_text(catalog,encoding="utf-8")
        current=self.catalog.current_manifest()
        manifest={"schema_version":"cti-rag-backup/1","objects":object_rows,"canonical_metadata_sha256":_sha(metadata.encode()),"snapshot_catalog_sha256":_sha(catalog.encode()),"current_manifest_id":None if current is None else current.manifest_id}
        (destination/"backup-manifest.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n",encoding="utf-8");return manifest
    def verify_backup(self,source):
        source=Path(source).resolve();manifest=json.loads((source/"backup-manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version")!="cti-rag-backup/1":raise RecoveryError("unsupported backup manifest")
        metadata=(source/"canonical-metadata.json").read_bytes();catalog=(source/"snapshot-catalog.json").read_bytes()
        if _sha(metadata)!=manifest["canonical_metadata_sha256"] or _sha(catalog)!=manifest["snapshot_catalog_sha256"]:raise RecoveryError("backup metadata checksum mismatch")
        for row in manifest["objects"]:
            data=(source/"objects"/row["relative_key"]).read_bytes()
            if len(data)!=row["size_bytes"] or _sha(data)!=row["digest"]:raise RecoveryError("backup object checksum mismatch")
        return manifest
    def restore_backup(self,source):
        source=Path(source).resolve();manifest=self.verify_backup(source)
        for row in manifest["objects"]:
            data=(source/"objects"/row["relative_key"]).read_bytes();ref=self.objects.put(data,row["retention_class"])
            if ref.digest!=row["digest"]:raise RecoveryError("restored object identity mismatch")
        self.metadata.restore_json((source/"canonical-metadata.json").read_text(encoding="utf-8"))
        self.catalog.restore_json((source/"snapshot-catalog.json").read_text(encoding="utf-8"))
        current=self.catalog.current_manifest()
        if manifest["current_manifest_id"]!=(None if current is None else current.manifest_id):raise RecoveryError("restored catalog pointer mismatch")
        return manifest
    def rebuild_fixture_index(self,path):
        current=self.catalog.current_manifest()
        if current is None:raise RecoveryError("no published manifest to rebuild")
        rows=[]
        for binding in current.projections:
            generation=self.catalog.get_generation(binding.generation_id)
            if generation is None:raise RecoveryError("manifest references missing generation")
            rows.append({"kind":generation.kind,"generation_id":generation.generation_id,"revision_uids":list(generation.revision_uids),"payloads":[{"payload_uid":p.payload_uid,"revision_uid":p.revision_uid,"locator_json":p.locator_json,"text_digest":p.text_digest} for p in generation.payloads]})
        payload={"schema_version":"fixture-derived-index/1","manifest_id":current.manifest_id,"corpus_digest":current.corpus_digest,"projections":rows}
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(payload,sort_keys=True,indent=2)+"\n",encoding="utf-8");return payload
    def rollback(self,manifest_id):return self.publisher.rollback(manifest_id)
    def propagate_tombstones(self,cache_invalidator,projection_cleanup):
        invalidated=0;cleaned=0
        for event_id,target_uid,_namespace in self.catalog.pending_invalidations():
            cache_invalidator(target_uid);self.catalog.ack_invalidation(event_id);invalidated+=1
        for task_id,target_uid,kind in self.catalog.pending_cleanup():
            projection_cleanup(kind,target_uid);self.catalog.ack_cleanup(task_id);cleaned+=1
        return {"invalidations":invalidated,"cleanup_tasks":cleaned}
    def health(self):
        current=self.catalog.current_manifest()
        return {
            "canonical_counts":self.metadata.counts(),"object_count":sum(1 for _ in self.objects.iter_refs()),
            "current_manifest_id":None if current is None else current.manifest_id,
            "revoked_count":len(self.catalog.revoked_uids()),"pending_invalidations":len(self.catalog.pending_invalidations()),"pending_cleanup":len(self.catalog.pending_cleanup()),
        }
