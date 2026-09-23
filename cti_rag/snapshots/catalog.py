"""DB-API snapshot catalog with atomic publication pointer, reader leases, backups, and revocations."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import json,sqlite3,uuid
from pathlib import Path
from cti_rag.contracts import namespaced_uid
from .models import PinnedSnapshot,ProjectionBinding,ProjectionGeneration,ProjectionPayload,SnapshotManifest

def _iso(v): return v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
def _dt(v): return datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(timezone.utc)
def _payload_dict(p): return {"payload_uid":p.payload_uid,"revision_uid":p.revision_uid,"locator_json":p.locator_json,"text_digest":p.text_digest,"original_text":p.original_text}
def _generation_dict(g):
    return {"generation_id":g.generation_id,"kind":g.kind,"revision_uids":list(g.revision_uids),"representation_versions":list(g.representation_versions),"checksum":g.checksum,"ready":g.ready,"visible":g.visible,"referential_integrity":g.referential_integrity,"quarantined_count":g.quarantined_count,"supported_query_capabilities":list(g.supported_query_capabilities),"created_at":_iso(g.created_at),"payloads":[_payload_dict(p) for p in g.payloads]}
def _generation_from(d):
    return ProjectionGeneration(d["generation_id"],d["kind"],tuple(d["revision_uids"]),tuple(d["representation_versions"]),d["checksum"],bool(d["ready"]),bool(d["visible"]),bool(d["referential_integrity"]),int(d["quarantined_count"]),tuple(d["supported_query_capabilities"]),_dt(d["created_at"]),tuple(ProjectionPayload(**p) for p in d.get("payloads",())))
def _manifest_dict(m):
    return {"manifest_id":m.manifest_id,"corpus_digest":m.corpus_digest,"revision_uids":list(m.revision_uids),"projections":[{"kind":p.kind,"generation_id":p.generation_id,"checksum":p.checksum,"representation_versions":list(p.representation_versions),"supported_query_capabilities":list(p.supported_query_capabilities)} for p in m.projections],"quarantined_count":m.quarantined_count,"supported_query_capabilities":list(m.supported_query_capabilities),"created_at":_iso(m.created_at),"schema_version":m.schema_version}
def _manifest_from(d):
    bindings=tuple(ProjectionBinding(p["kind"],p["generation_id"],p["checksum"],tuple(p["representation_versions"]),tuple(p["supported_query_capabilities"])) for p in d["projections"])
    return SnapshotManifest(d["manifest_id"],d["corpus_digest"],tuple(d["revision_uids"]),bindings,int(d["quarantined_count"]),tuple(d["supported_query_capabilities"]),_dt(d["created_at"]),d.get("schema_version","snapshot-manifest/2"))

SCHEMA=(
"CREATE TABLE IF NOT EXISTS projection_generations (generation_id VARCHAR(160) PRIMARY KEY, kind VARCHAR(64) NOT NULL, body_json TEXT NOT NULL, status VARCHAR(24) NOT NULL, created_at VARCHAR(40) NOT NULL)",
"CREATE TABLE IF NOT EXISTS snapshot_manifests (manifest_id VARCHAR(160) PRIMARY KEY, body_json TEXT NOT NULL, status VARCHAR(24) NOT NULL, created_at VARCHAR(40) NOT NULL)",
"CREATE TABLE IF NOT EXISTS catalog_pointer (slot VARCHAR(32) PRIMARY KEY, manifest_id VARCHAR(160) NOT NULL, updated_at VARCHAR(40) NOT NULL)",
"CREATE TABLE IF NOT EXISTS reader_leases (lease_id VARCHAR(64) PRIMARY KEY, manifest_id VARCHAR(160) NOT NULL, expires_at VARCHAR(40) NOT NULL, released INTEGER NOT NULL DEFAULT 0)",
"CREATE TABLE IF NOT EXISTS revocation_overlay (target_uid VARCHAR(160) PRIMARY KEY, reason TEXT NOT NULL, event_id VARCHAR(160) NOT NULL, admitted_at VARCHAR(40) NOT NULL, active INTEGER NOT NULL)",
"CREATE TABLE IF NOT EXISTS cache_invalidations (event_id VARCHAR(160) PRIMARY KEY, target_uid VARCHAR(160) NOT NULL, namespace VARCHAR(80) NOT NULL, status VARCHAR(24) NOT NULL, created_at VARCHAR(40) NOT NULL)",
"CREATE TABLE IF NOT EXISTS cleanup_tasks (task_id VARCHAR(160) PRIMARY KEY, target_uid VARCHAR(160) NOT NULL, projection_kind VARCHAR(64) NOT NULL, status VARCHAR(24) NOT NULL, created_at VARCHAR(40) NOT NULL, acked_at VARCHAR(40) NULL)"
)

class SnapshotCatalogStore:
    def __init__(self,connection_factory,dialect="sqlite"):
        self._connection_factory=connection_factory; self.dialect=dialect; self.initialize()
    @classmethod
    def sqlite(cls,path):
        path=str(Path(path)); return cls(lambda:sqlite3.connect(path),"sqlite")
    @classmethod
    def from_existing_manager(cls,manager):
        return cls(manager.engine.raw_connection,getattr(manager.engine.dialect,"name","mysql"))
    def _sql(self,sql): return sql if self.dialect=="sqlite" else sql.replace("?","%s")
    @contextmanager
    def transaction(self):
        conn=self._connection_factory(); cur=conn.cursor()
        try:
            if self.dialect=="sqlite": cur.execute("BEGIN IMMEDIATE")
            yield cur; conn.commit()
        except Exception:
            conn.rollback(); raise
        finally:
            try: cur.close()
            finally: conn.close()
    def execute(self,cur,sql,params=()): return cur.execute(self._sql(sql),params)
    def initialize(self):
        conn=self._connection_factory(); cur=conn.cursor()
        try:
            for ddl in SCHEMA: cur.execute(ddl)
            conn.commit()
        finally:
            cur.close(); conn.close()
    def stage_generation(self,generation):
        body=json.dumps(_generation_dict(generation),sort_keys=True,separators=(",",":"))
        with self.transaction() as cur:
            self.execute(cur,"SELECT body_json,status FROM projection_generations WHERE generation_id=?",(generation.generation_id,)); row=cur.fetchone()
            if row:
                if row[0]!=body: raise ValueError("generation id is immutable and already refers to different content")
                return generation
            self.execute(cur,"INSERT INTO projection_generations (generation_id,kind,body_json,status,created_at) VALUES (?,?,?,?,?)",(generation.generation_id,generation.kind,body,"staged",_iso(generation.created_at)))
        return generation
    def get_generation(self,generation_id):
        conn=self._connection_factory(); cur=conn.cursor()
        try:
            self.execute(cur,"SELECT body_json FROM projection_generations WHERE generation_id=?",(generation_id,)); row=cur.fetchone()
            return None if row is None else _generation_from(json.loads(row[0]))
        finally: cur.close(); conn.close()
    def generation_status(self,generation_id):
        conn=self._connection_factory(); cur=conn.cursor()
        try:self.execute(cur,"SELECT status FROM projection_generations WHERE generation_id=?",(generation_id,)); row=cur.fetchone(); return None if row is None else row[0]
        finally:cur.close(); conn.close()
    def mark_generation_failed(self,generation_id):
        with self.transaction() as cur:self.execute(cur,"UPDATE projection_generations SET status=? WHERE generation_id=?",("failed",generation_id))
    def store_manifest(self,manifest):
        body=json.dumps(_manifest_dict(manifest),sort_keys=True,separators=(",",":"))
        with self.transaction() as cur:
            self.execute(cur,"SELECT body_json FROM snapshot_manifests WHERE manifest_id=?",(manifest.manifest_id,)); row=cur.fetchone()
            if row:
                if row[0]!=body: raise ValueError("manifest id collision with different content")
                return manifest
            self.execute(cur,"INSERT INTO snapshot_manifests (manifest_id,body_json,status,created_at) VALUES (?,?,?,?)",(manifest.manifest_id,body,"staged",_iso(manifest.created_at)))
        return manifest
    def get_manifest(self,manifest_id):
        conn=self._connection_factory(); cur=conn.cursor()
        try:self.execute(cur,"SELECT body_json FROM snapshot_manifests WHERE manifest_id=?",(manifest_id,)); row=cur.fetchone(); return None if row is None else _manifest_from(json.loads(row[0]))
        finally:cur.close(); conn.close()
    def publish_pointer(self,manifest_id):
        manifest=self.get_manifest(manifest_id)
        if manifest is None: raise ValueError("cannot publish unknown manifest")
        now=_iso(datetime.now(timezone.utc))
        with self.transaction() as cur:
            self.execute(cur,"SELECT manifest_id FROM catalog_pointer WHERE slot=?",("current",)); row=cur.fetchone()
            if row is None:self.execute(cur,"INSERT INTO catalog_pointer (slot,manifest_id,updated_at) VALUES (?,?,?)",("current",manifest_id,now))
            else:self.execute(cur,"UPDATE catalog_pointer SET manifest_id=?,updated_at=? WHERE slot=?",(manifest_id,now,"current"))
            self.execute(cur,"UPDATE snapshot_manifests SET status=? WHERE manifest_id=?",("published",manifest_id))
    def current_manifest(self):
        conn=self._connection_factory(); cur=conn.cursor()
        try:self.execute(cur,"SELECT manifest_id FROM catalog_pointer WHERE slot=?",("current",)); row=cur.fetchone(); return None if row is None else self.get_manifest(row[0])
        finally:cur.close(); conn.close()
    def generation_for_manifest(self,manifest_id,kind):
        manifest=self.get_manifest(manifest_id)
        return None if manifest is None else manifest.generation_id(kind)
    def pin_current(self,scope=None,ttl_seconds=30,now=None):
        now=now or datetime.now(timezone.utc); manifest=self.current_manifest()
        if manifest is None: raise RuntimeError("no published snapshot")
        lease_id=uuid.uuid4().hex; expires=now+timedelta(seconds=ttl_seconds)
        with self.transaction() as cur:self.execute(cur,"INSERT INTO reader_leases (lease_id,manifest_id,expires_at,released) VALUES (?,?,?,0)",(lease_id,manifest.manifest_id,_iso(expires)))
        return PinnedSnapshot(manifest,lease_id,expires)
    def pin_manifest(self,manifest_id,scope=None,ttl_seconds=30,now=None):
        now=now or datetime.now(timezone.utc); manifest=self.get_manifest(manifest_id)
        if manifest is None: raise KeyError(manifest_id)
        lease_id=uuid.uuid4().hex; expires=now+timedelta(seconds=ttl_seconds)
        with self.transaction() as cur:self.execute(cur,"INSERT INTO reader_leases (lease_id,manifest_id,expires_at,released) VALUES (?,?,?,0)",(lease_id,manifest.manifest_id,_iso(expires)))
        return PinnedSnapshot(manifest,lease_id,expires)
    def resolve(self,manifest_id,scope=None):
        manifest=self.get_manifest(manifest_id)
        if manifest is None: raise KeyError(manifest_id)
        return manifest.to_ref()
    def release_lease(self,lease_id):
        with self.transaction() as cur:self.execute(cur,"UPDATE reader_leases SET released=1 WHERE lease_id=?",(lease_id,))
    def cleanup_expired_leases(self,now=None):
        now=now or datetime.now(timezone.utc)
        with self.transaction() as cur:
            self.execute(cur,"DELETE FROM reader_leases WHERE released=1 OR expires_at<=?",(_iso(now),))
    def _active_manifest_ids(self,now=None):
        now=now or datetime.now(timezone.utc); ids=set()
        current=self.current_manifest()
        if current: ids.add(current.manifest_id)
        conn=self._connection_factory(); cur=conn.cursor()
        try:
            self.execute(cur,"SELECT DISTINCT manifest_id FROM reader_leases WHERE released=0 AND expires_at>?",(_iso(now),)); ids.update(r[0] for r in cur.fetchall())
            return ids
        finally:cur.close(); conn.close()
    def generation_in_use(self,generation_id,now=None):
        for manifest_id in self._active_manifest_ids(now):
            manifest=self.get_manifest(manifest_id)
            if manifest and generation_id in tuple(p.generation_id for p in manifest.projections): return True
        return False
    def cleanup_failed_generation(self,generation_id,now=None):
        if self.generation_status(generation_id)!="failed": return False
        if self.generation_in_use(generation_id,now): return False
        with self.transaction() as cur:self.execute(cur,"DELETE FROM projection_generations WHERE generation_id=?",(generation_id,))
        return True
    def cleanup_generation(self,generation_id,now=None):
        if self.generation_in_use(generation_id,now): return False
        with self.transaction() as cur:self.execute(cur,"DELETE FROM projection_generations WHERE generation_id=?",(generation_id,))
        return True
    def admit_revocation(self,target_uid,reason,dependent_uids=(),projection_kinds=()):
        admitted=datetime.now(timezone.utc); event_id=namespaced_uid("rvk","snapshot.revocation",{"target_uid":target_uid,"reason":reason})
        targets=tuple(dict.fromkeys((target_uid,)+tuple(dependent_uids)))
        with self.transaction() as cur:
            for uid in targets:
                self.execute(cur,"SELECT target_uid FROM revocation_overlay WHERE target_uid=?",(uid,)); row=cur.fetchone()
                if row is None:self.execute(cur,"INSERT INTO revocation_overlay (target_uid,reason,event_id,admitted_at,active) VALUES (?,?,?,?,1)",(uid,reason,event_id,_iso(admitted)))
                else:self.execute(cur,"UPDATE revocation_overlay SET reason=?,event_id=?,admitted_at=?,active=1 WHERE target_uid=?",(reason,event_id,_iso(admitted),uid))
                invalidation=namespaced_uid("inv","cache.revocation",{"target_uid":uid,"event_id":event_id})
                self.execute(cur,"SELECT event_id FROM cache_invalidations WHERE event_id=?",(invalidation,))
                if cur.fetchone() is None:self.execute(cur,"INSERT INTO cache_invalidations (event_id,target_uid,namespace,status,created_at) VALUES (?,?,?,?,?)",(invalidation,uid,"all","pending",_iso(admitted)))
                for kind in projection_kinds:
                    task=namespaced_uid("cln","projection.revocation",{"target_uid":uid,"kind":kind,"event_id":event_id})
                    self.execute(cur,"SELECT task_id FROM cleanup_tasks WHERE task_id=?",(task,))
                    if cur.fetchone() is None:self.execute(cur,"INSERT INTO cleanup_tasks (task_id,target_uid,projection_kind,status,created_at,acked_at) VALUES (?,?,?,?,?,NULL)",(task,uid,kind,"pending",_iso(admitted)))
        return event_id
    def is_revoked(self,uid):
        conn=self._connection_factory(); cur=conn.cursor()
        try:self.execute(cur,"SELECT active FROM revocation_overlay WHERE target_uid=?",(uid,)); row=cur.fetchone(); return bool(row and row[0])
        finally:cur.close(); conn.close()
    def revoked_uids(self):
        conn=self._connection_factory(); cur=conn.cursor()
        try:cur.execute("SELECT target_uid FROM revocation_overlay WHERE active=1 ORDER BY target_uid"); return tuple(r[0] for r in cur.fetchall())
        finally:cur.close(); conn.close()
    def pending_invalidations(self):
        conn=self._connection_factory(); cur=conn.cursor()
        try:cur.execute("SELECT event_id,target_uid,namespace FROM cache_invalidations WHERE status='pending' ORDER BY event_id"); return tuple(cur.fetchall())
        finally:cur.close(); conn.close()
    def ack_invalidation(self,event_id):
        with self.transaction() as cur:self.execute(cur,"UPDATE cache_invalidations SET status='acked' WHERE event_id=?",(event_id,))
    def pending_cleanup(self,target_uid=None):
        conn=self._connection_factory(); cur=conn.cursor()
        try:
            if target_uid is None:cur.execute("SELECT task_id,target_uid,projection_kind FROM cleanup_tasks WHERE status='pending' ORDER BY task_id")
            else:self.execute(cur,"SELECT task_id,target_uid,projection_kind FROM cleanup_tasks WHERE status='pending' AND target_uid=? ORDER BY task_id",(target_uid,))
            return tuple(cur.fetchall())
        finally:cur.close(); conn.close()
    def ack_cleanup(self,task_id,now=None):
        with self.transaction() as cur:self.execute(cur,"UPDATE cleanup_tasks SET status='acked',acked_at=? WHERE task_id=?",(_iso(now or datetime.now(timezone.utc)),task_id))
    def backup_json(self):
        conn=self._connection_factory(); cur=conn.cursor()
        try:
            out={"schema_version":"snapshot-catalog-backup/1"}
            cur.execute("SELECT generation_id,body_json,status FROM projection_generations ORDER BY generation_id"); out["generations"]=[{"generation_id":a,"body":json.loads(b),"status":c} for a,b,c in cur.fetchall()]
            cur.execute("SELECT manifest_id,body_json,status FROM snapshot_manifests ORDER BY manifest_id"); out["manifests"]=[{"manifest_id":a,"body":json.loads(b),"status":c} for a,b,c in cur.fetchall()]
            cur.execute("SELECT slot,manifest_id,updated_at FROM catalog_pointer ORDER BY slot"); out["pointers"]=[list(r) for r in cur.fetchall()]
            cur.execute("SELECT target_uid,reason,event_id,admitted_at,active FROM revocation_overlay ORDER BY target_uid"); out["revocations"]=[list(r) for r in cur.fetchall()]
            cur.execute("SELECT event_id,target_uid,namespace,status,created_at FROM cache_invalidations ORDER BY event_id"); out["invalidations"]=[list(r) for r in cur.fetchall()]
            cur.execute("SELECT task_id,target_uid,projection_kind,status,created_at,acked_at FROM cleanup_tasks ORDER BY task_id"); out["cleanup_tasks"]=[list(r) for r in cur.fetchall()]
            return json.dumps(out,sort_keys=True,separators=(",",":"))
        finally:cur.close(); conn.close()
    def restore_json(self,backup):
        data=json.loads(backup)
        if data.get("schema_version")!="snapshot-catalog-backup/1": raise ValueError("unsupported catalog backup schema")
        with self.transaction() as cur:
            for table in ("projection_generations","snapshot_manifests","catalog_pointer","reader_leases","revocation_overlay","cache_invalidations","cleanup_tasks"): cur.execute(f"DELETE FROM {table}")
            for row in data["generations"]:
                body=json.dumps(row["body"],sort_keys=True,separators=(",",":")); self.execute(cur,"INSERT INTO projection_generations (generation_id,kind,body_json,status,created_at) VALUES (?,?,?,?,?)",(row["generation_id"],row["body"]["kind"],body,row["status"],row["body"]["created_at"]))
            for row in data["manifests"]:
                body=json.dumps(row["body"],sort_keys=True,separators=(",",":")); self.execute(cur,"INSERT INTO snapshot_manifests (manifest_id,body_json,status,created_at) VALUES (?,?,?,?)",(row["manifest_id"],body,row["status"],row["body"]["created_at"]))
            for row in data["pointers"]: self.execute(cur,"INSERT INTO catalog_pointer (slot,manifest_id,updated_at) VALUES (?,?,?)",tuple(row))
            for row in data["revocations"]: self.execute(cur,"INSERT INTO revocation_overlay (target_uid,reason,event_id,admitted_at,active) VALUES (?,?,?,?,?)",tuple(row))
            for row in data["invalidations"]: self.execute(cur,"INSERT INTO cache_invalidations (event_id,target_uid,namespace,status,created_at) VALUES (?,?,?,?,?)",tuple(row))
            for row in data["cleanup_tasks"]: self.execute(cur,"INSERT INTO cleanup_tasks (task_id,target_uid,projection_kind,status,created_at,acked_at) VALUES (?,?,?,?,?,?)",tuple(row))
