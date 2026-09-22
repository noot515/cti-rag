"""Portable DB-API canonical metadata store with atomic metadata + outbox writes.

The same implementation can use SQLite for deterministic fixtures or the existing
legacy SQLAlchemy manager's pooled DB-API connection via ``from_existing_manager``.
No SQLAlchemy import occurs at module import time.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime,timezone
import json,sqlite3
from pathlib import Path
from typing import Callable,Iterable,Optional
from cti_rag.contracts import canonical_json_bytes,namespaced_uid
from cti_rag.ingestion.models import CanonicalBundle,OutboxEvent,QuarantineRecord,SourceManifest

def _iso(v):
    if isinstance(v,datetime): return v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    return v
def _json(v): return canonical_json_bytes(v).decode("utf-8")

SCHEMA=(
"CREATE TABLE IF NOT EXISTS source_manifests (source_id VARCHAR(160) PRIMARY KEY, manifest_json TEXT NOT NULL, manifest_digest VARCHAR(64) NOT NULL, created_at VARCHAR(40) NOT NULL)",
"CREATE TABLE IF NOT EXISTS raw_snapshots (snapshot_uid VARCHAR(160) PRIMARY KEY, source_id VARCHAR(160) NOT NULL, record_key VARCHAR(255) NOT NULL, object_digest VARCHAR(64) NOT NULL, size_bytes BIGINT NOT NULL, retention_class VARCHAR(64) NOT NULL, upstream_cursor TEXT NULL, created_at VARCHAR(40) NOT NULL)",
"CREATE TABLE IF NOT EXISTS source_objects (object_uid VARCHAR(160) PRIMARY KEY, source_id VARCHAR(160) NOT NULL, stable_upstream_id VARCHAR(255) NOT NULL, object_type VARCHAR(128) NOT NULL)",
"CREATE TABLE IF NOT EXISTS revisions (revision_uid VARCHAR(160) PRIMARY KEY, object_uid VARCHAR(160) NOT NULL, raw_digest VARCHAR(64) NOT NULL, snapshot_uid VARCHAR(160) NOT NULL, upstream_version TEXT NULL, temporal_json TEXT NOT NULL, policy_json TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)",
"CREATE TABLE IF NOT EXISTS artifacts (artifact_uid VARCHAR(160) PRIMARY KEY, revision_uid VARCHAR(160) NOT NULL, normalized_digest VARCHAR(64) NOT NULL, object_digest VARCHAR(64) NOT NULL, retention_class VARCHAR(64) NOT NULL, schema_version VARCHAR(128) NOT NULL)",
"CREATE TABLE IF NOT EXISTS retrieval_observations (observation_id VARCHAR(160) PRIMARY KEY, revision_uid VARCHAR(160) NOT NULL, retrieved_at VARCHAR(40) NOT NULL, connector_fingerprint TEXT NOT NULL)",
"CREATE TABLE IF NOT EXISTS ingestion_runs (run_id VARCHAR(160) PRIMARY KEY, source_id VARCHAR(160) NOT NULL, status VARCHAR(32) NOT NULL, started_at VARCHAR(40) NOT NULL, finished_at VARCHAR(40) NULL)",
"CREATE TABLE IF NOT EXISTS ingestion_checkpoints (source_id VARCHAR(160) PRIMARY KEY, cursor TEXT NULL, committed_run_id VARCHAR(160) NOT NULL, updated_at VARCHAR(40) NOT NULL)",
"CREATE TABLE IF NOT EXISTS quarantines (quarantine_id VARCHAR(160) PRIMARY KEY, run_id VARCHAR(160) NOT NULL, source_id VARCHAR(160) NOT NULL, record_key VARCHAR(255) NOT NULL, reason TEXT NOT NULL, raw_digest VARCHAR(64) NULL, object_digest VARCHAR(64) NULL, created_at VARCHAR(40) NOT NULL)",
"CREATE TABLE IF NOT EXISTS outbox (event_id VARCHAR(160) PRIMARY KEY, kind VARCHAR(80) NOT NULL, aggregate_id VARCHAR(160) NOT NULL, idempotency_key VARCHAR(160) NOT NULL, payload_json TEXT NOT NULL, status VARCHAR(24) NOT NULL, attempts INTEGER NOT NULL, available_at VARCHAR(40) NOT NULL, last_error TEXT NULL, created_at VARCHAR(40) NOT NULL)",
"CREATE TABLE IF NOT EXISTS processed_events (idempotency_key VARCHAR(160) PRIMARY KEY, processed_at VARCHAR(40) NOT NULL)",
"CREATE TABLE IF NOT EXISTS dead_letters (event_id VARCHAR(160) PRIMARY KEY, payload_json TEXT NOT NULL, reason TEXT NOT NULL, attempts INTEGER NOT NULL, created_at VARCHAR(40) NOT NULL)",
"CREATE TABLE IF NOT EXISTS dependencies (parent_uid VARCHAR(160) NOT NULL, child_uid VARCHAR(160) NOT NULL, kind VARCHAR(64) NOT NULL, PRIMARY KEY(parent_uid,child_uid,kind))",
"CREATE TABLE IF NOT EXISTS revocations (event_id VARCHAR(160) PRIMARY KEY, target_uid VARCHAR(160) NOT NULL, reason TEXT NOT NULL, created_at VARCHAR(40) NOT NULL)"
)

class CanonicalMetadataStore:
    def __init__(self,connection_factory:Callable[[],object],dialect="sqlite",object_exists:Optional[Callable[[object],bool]]=None):
        self._connection_factory=connection_factory; self.dialect=dialect; self._object_exists=object_exists
        self.initialize()
    @classmethod
    def sqlite(cls,path,object_exists=None):
        path=str(Path(path)); return cls(lambda: sqlite3.connect(path),"sqlite",object_exists)
    @classmethod
    def from_existing_manager(cls,manager,object_exists=None):
        return cls(manager.engine.raw_connection,getattr(manager.engine.dialect,"name","mysql"),object_exists)
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
            try:cur.close()
            finally:conn.close()
    def _exists(self,cur,table,key_col,key):
        self.execute(cur,f"SELECT 1 FROM {table} WHERE {key_col}=?",(key,)); return cur.fetchone() is not None
    def _insert_if_absent(self,cur,table,key_col,key,columns,values):
        if self._exists(cur,table,key_col,key): return False
        placeholders=",".join("?" for _ in columns); self.execute(cur,f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",values); return True
    def put_manifest(self,manifest:SourceManifest):
        payload=asdict(manifest); digest=__import__('hashlib').sha256(_json(payload).encode()).hexdigest(); now=_iso(datetime.now(timezone.utc))
        with self.transaction() as cur:
            self._insert_if_absent(cur,"source_manifests","source_id",manifest.source_id,("source_id","manifest_json","manifest_digest","created_at"),(manifest.source_id,_json(payload),digest,now))
    def begin_run(self,run_id,source_id,started_at):
        with self.transaction() as cur:self._insert_if_absent(cur,"ingestion_runs","run_id",run_id,("run_id","source_id","status","started_at","finished_at"),(run_id,source_id,"running",_iso(started_at),None))
    def finish_run(self,run_id,status,finished_at):
        with self.transaction() as cur:self.execute(cur,"UPDATE ingestion_runs SET status=?, finished_at=? WHERE run_id=?",(status,_iso(finished_at),run_id))
    def quarantine(self,q:QuarantineRecord):
        with self.transaction() as cur:self._insert_if_absent(cur,"quarantines","quarantine_id",q.quarantine_id,("quarantine_id","run_id","source_id","record_key","reason","raw_digest","object_digest","created_at"),(q.quarantine_id,q.run_id,q.source_id,q.record_key,q.reason,q.raw_digest,q.object_digest,_iso(q.created_at)))
    def commit_bundle(self,b:CanonicalBundle):
        if self._object_exists:
            if not self._object_exists(b.raw_snapshot.object_ref): raise FileNotFoundError("raw object missing before metadata commit")
            if not self._object_exists(b.normalized_ref): raise FileNotFoundError("normalized object missing before metadata commit")
        with self.transaction() as cur:
            rs=b.raw_snapshot; so=b.source_object; rev=b.revision; art=b.artifact; obs=b.observation; ev=b.outbox
            self._insert_if_absent(cur,"raw_snapshots","snapshot_uid",rs.snapshot_uid,("snapshot_uid","source_id","record_key","object_digest","size_bytes","retention_class","upstream_cursor","created_at"),(rs.snapshot_uid,rs.source_id,rs.record_key,rs.object_ref.digest,rs.object_ref.size_bytes,rs.object_ref.retention_class,rs.upstream_cursor,_iso(rs.created_at)))
            self._insert_if_absent(cur,"source_objects","object_uid",so.object_uid,("object_uid","source_id","stable_upstream_id","object_type"),(so.object_uid,b.source_id,so.stable_upstream_id,so.upstream_object_type))
            self._insert_if_absent(cur,"revisions","revision_uid",rev.revision_uid,("revision_uid","object_uid","raw_digest","snapshot_uid","upstream_version","temporal_json","policy_json","revoked"),(rev.revision_uid,rev.object_uid,rev.raw_digest,rs.snapshot_uid,rev.upstream_version,_json(rev.temporal),_json(so.policy),0))
            self._insert_if_absent(cur,"artifacts","artifact_uid",art.artifact_uid,("artifact_uid","revision_uid","normalized_digest","object_digest","retention_class","schema_version"),(art.artifact_uid,art.revision_uid,art.normalized_digest,b.normalized_ref.digest,b.normalized_ref.retention_class,art.content_schema_version))
            self._insert_if_absent(cur,"retrieval_observations","observation_id",obs.observation_id,("observation_id","revision_uid","retrieved_at","connector_fingerprint"),(obs.observation_id,rev.revision_uid,_iso(obs.retrieved_at),_json(obs.connector_fingerprint.identity_material())))
            for parent,child,kind in b.dependencies:
                self.execute(cur,"SELECT 1 FROM dependencies WHERE parent_uid=? AND child_uid=? AND kind=?",(parent,child,kind))
                if cur.fetchone() is None:self.execute(cur,"INSERT INTO dependencies (parent_uid,child_uid,kind) VALUES (?,?,?)",(parent,child,kind))
            self._insert_if_absent(cur,"outbox","event_id",ev.event_id,("event_id","kind","aggregate_id","idempotency_key","payload_json","status","attempts","available_at","last_error","created_at"),(ev.event_id,ev.kind,ev.aggregate_id,ev.idempotency_key,ev.payload_json,ev.status,ev.attempts,_iso(ev.available_at),ev.last_error,_iso(datetime.now(timezone.utc))))
    def advance_checkpoint(self,source_id,cursor,run_id,updated_at):
        with self.transaction() as cur:
            self.execute(cur,"SELECT 1 FROM ingestion_checkpoints WHERE source_id=?",(source_id,))
            if cur.fetchone() is None:self.execute(cur,"INSERT INTO ingestion_checkpoints (source_id,cursor,committed_run_id,updated_at) VALUES (?,?,?,?)",(source_id,cursor,run_id,_iso(updated_at)))
            else:self.execute(cur,"UPDATE ingestion_checkpoints SET cursor=?, committed_run_id=?, updated_at=? WHERE source_id=?",(cursor,run_id,_iso(updated_at),source_id))
    def checkpoint(self,source_id):
        conn=self._connection_factory(); cur=conn.cursor()
        try:
            self.execute(cur,"SELECT cursor,committed_run_id,updated_at FROM ingestion_checkpoints WHERE source_id=?",(source_id,)); return cur.fetchone()
        finally:cur.close(); conn.close()
    def counts(self):
        conn=self._connection_factory(); cur=conn.cursor(); out={}
        try:
            for table in ("source_manifests","raw_snapshots","source_objects","revisions","artifacts","retrieval_observations","quarantines","outbox","dead_letters","revocations"):
                cur.execute(f"SELECT COUNT(*) FROM {table}"); out[table]=int(cur.fetchone()[0])
            return out
        finally:cur.close(); conn.close()
    def referenced_object_digests(self):
        conn=self._connection_factory(); cur=conn.cursor(); out=set()
        try:
            cur.execute("SELECT object_digest FROM raw_snapshots"); out.update(r[0] for r in cur.fetchall())
            cur.execute("SELECT object_digest FROM artifacts"); out.update(r[0] for r in cur.fetchall())
            cur.execute("SELECT object_digest FROM quarantines WHERE object_digest IS NOT NULL"); out.update(r[0] for r in cur.fetchall())
            return frozenset(out)
        finally:cur.close(); conn.close()
    def pending_outbox(self,limit=100):
        conn=self._connection_factory(); cur=conn.cursor()
        try:
            cur.execute(self._sql("SELECT event_id,kind,aggregate_id,idempotency_key,payload_json,status,attempts,available_at,last_error FROM outbox WHERE status=? ORDER BY created_at LIMIT ?"),("pending",limit)); rows=cur.fetchall()
            return tuple(OutboxEvent(r[0],r[1],r[2],r[3],r[4],r[5],int(r[6]),datetime.fromisoformat(r[7].replace("Z","+00:00")),r[8]) for r in rows)
        finally:cur.close(); conn.close()
    def event_processed(self,key):
        conn=self._connection_factory(); cur=conn.cursor()
        try:self.execute(cur,"SELECT 1 FROM processed_events WHERE idempotency_key=?",(key,)); return cur.fetchone() is not None
        finally:cur.close(); conn.close()
    def mark_event_done(self,event:OutboxEvent):
        now=_iso(datetime.now(timezone.utc))
        with self.transaction() as cur:
            self._insert_if_absent(cur,"processed_events","idempotency_key",event.idempotency_key,("idempotency_key","processed_at"),(event.idempotency_key,now))
            self.execute(cur,"UPDATE outbox SET status=?, last_error=? WHERE event_id=?",("done",None,event.event_id))
    def fail_event(self,event:OutboxEvent,error,max_attempts):
        attempts=event.attempts+1; now=_iso(datetime.now(timezone.utc))
        with self.transaction() as cur:
            if attempts>=max_attempts:
                self.execute(cur,"UPDATE outbox SET status=?, attempts=?, last_error=? WHERE event_id=?",("dead_letter",attempts,error,event.event_id))
                self._insert_if_absent(cur,"dead_letters","event_id",event.event_id,("event_id","payload_json","reason","attempts","created_at"),(event.event_id,event.payload_json,error,attempts,now))
            else:self.execute(cur,"UPDATE outbox SET attempts=?, last_error=? WHERE event_id=?",(attempts,error,event.event_id))
    def add_revocation(self,target_uid,reason):
        event_id=namespaced_uid("del","evidence.revocation",{"target_uid":target_uid,"reason":reason}); now=datetime.now(timezone.utc); cleanup_id=namespaced_uid("evt","projection.cleanup",{"target_uid":target_uid,"reason":reason})
        payload=_json({"target_uid":target_uid,"reason":reason})
        with self.transaction() as cur:
            self._insert_if_absent(cur,"revocations","event_id",event_id,("event_id","target_uid","reason","created_at"),(event_id,target_uid,reason,_iso(now)))
            self._insert_if_absent(cur,"outbox","event_id",cleanup_id,("event_id","kind","aggregate_id","idempotency_key","payload_json","status","attempts","available_at","last_error","created_at"),(cleanup_id,"projection_cleanup",target_uid,cleanup_id,payload,"pending",0,_iso(now),None,_iso(now)))
            self.execute(cur,"UPDATE revisions SET revoked=1 WHERE revision_uid=?",(target_uid,))
        return event_id
    def dependents(self,parent_uid):
        conn=self._connection_factory(); cur=conn.cursor(); seen=set(); frontier=[parent_uid]
        try:
            while frontier:
                p=frontier.pop(); self.execute(cur,"SELECT child_uid FROM dependencies WHERE parent_uid=?",(p,))
                for (child,) in cur.fetchall():
                    if child not in seen: seen.add(child); frontier.append(child)
            return tuple(sorted(seen))
        finally:cur.close(); conn.close()
