"""Generation state, atomic active pointers, and pinned snapshot handles."""
from __future__ import annotations
from dataclasses import dataclass
from packages.evidence.ids import canonical_hash, canonical_json
from packages.evidence.policy import ResolvedScope
from packages.evidence.publication_migrations import apply_publication_migrations
from packages.evidence.schema import SnapshotRef
from packages.evidence.store import EvidenceStore, ImmutableRevisionConflict
from packages.indexing.manifests import GenerationManifest, ProjectionReceipt

class SnapshotPublicationError(RuntimeError): pass
class ReceiptMismatch(SnapshotPublicationError): pass
class PublicationNotReady(SnapshotPublicationError): pass
class EvidenceWithdrawn(PermissionError): pass

class SnapshotCatalog:
    def __init__(self,store:EvidenceStore):
        self.store=store; self.db=store.connection
        with self.store.writer_lock(): apply_publication_migrations(self.db)
    def _job_id(self,m): return canonical_hash(['publication-job-v1',m.manifest_sha256])
    def _member_exists(self,m,member):
        if member.kind=='object':
            row=self.db.execute('SELECT object_uid FROM object_revisions WHERE domain=? AND scope_id=? AND revision_uid=?',(m.domain,m.scope_id,member.revision_uid)).fetchone(); return bool(row and row['object_uid']==member.evidence_uid)
        if member.kind=='relation':
            row=self.db.execute('SELECT relation_uid FROM relation_revisions WHERE domain=? AND scope_id=? AND revision_uid=?',(m.domain,m.scope_id,member.revision_uid)).fetchone(); return bool(row and row['relation_uid']==member.evidence_uid)
        row=self.db.execute('SELECT chunk_uid FROM chunks WHERE domain=? AND scope_id=? AND chunk_uid=?',(m.domain,m.scope_id,member.evidence_uid)).fetchone(); return bool(row and member.revision_uid==member.evidence_uid)
    def register_generation(self,m:GenerationManifest)->str:
        job=self._job_id(m)
        with self.store.writer_lock():
            try:
                self.db.execute('BEGIN IMMEDIATE')
                snap=self.db.execute('SELECT manifest_sha256 FROM snapshots WHERE domain=? AND scope_id=? AND snapshot_id=?',(m.domain,m.scope_id,m.generation_id)).fetchone()
                if snap and snap['manifest_sha256']!=m.manifest_sha256: raise ImmutableRevisionConflict('snapshot generation hash mismatch')
                if not snap: self.db.execute("INSERT INTO snapshots(domain,scope_id,snapshot_id,manifest_sha256,active,created_at) VALUES(?,?,?,?,0,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",(m.domain,m.scope_id,m.generation_id,m.manifest_sha256))
                for member in m.membership:
                    if not self._member_exists(m,member): raise SnapshotPublicationError(f'manifest member does not exist: {member.kind}:{member.revision_uid}')
                    self.db.execute('INSERT OR IGNORE INTO snapshot_membership(domain,scope_id,snapshot_id,evidence_kind,evidence_uid,revision_uid) VALUES(?,?,?,?,?,?)',(m.domain,m.scope_id,m.generation_id,member.kind,member.evidence_uid,member.revision_uid))
                observed={(r['evidence_kind'],r['evidence_uid'],r['revision_uid']) for r in self.db.execute('SELECT evidence_kind,evidence_uid,revision_uid FROM snapshot_membership WHERE domain=? AND scope_id=? AND snapshot_id=?',(m.domain,m.scope_id,m.generation_id))}
                expected={(x.kind,x.evidence_uid,x.revision_uid) for x in m.membership}
                if observed!=expected: raise SnapshotPublicationError('snapshot membership differs from generation manifest')
                existing=self.db.execute('SELECT manifest_sha256 FROM generation_manifests WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?',(m.domain,m.scope_id,m.corpus_id,m.generation_id)).fetchone()
                if existing and existing['manifest_sha256']!=m.manifest_sha256: raise ImmutableRevisionConflict('generation id conflicts with manifest')
                self.db.execute("INSERT OR IGNORE INTO generation_manifests(domain,scope_id,corpus_id,generation_id,manifest_sha256,manifest_json,state,created_at) VALUES(?,?,?,?,?,?, 'building', strftime('%Y-%m-%dT%H:%M:%fZ','now'))",(m.domain,m.scope_id,m.corpus_id,m.generation_id,m.manifest_sha256,canonical_json(m.model_dump(mode='json'))))
                self.db.execute("INSERT OR IGNORE INTO publication_jobs(domain,scope_id,corpus_id,generation_id,job_id,status,requested_at) VALUES(?,?,?,?,?,'building',strftime('%Y-%m-%dT%H:%M:%fZ','now'))",(m.domain,m.scope_id,m.corpus_id,m.generation_id,job))
                for p in m.enabled_projections:
                    self.db.execute("INSERT OR IGNORE INTO projection_jobs(domain,scope_id,corpus_id,generation_id,backend,required,status,manifest_sha256,requested_at) VALUES(?,?,?,?,?,?, 'pending', ?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",(m.domain,m.scope_id,m.corpus_id,m.generation_id,p.backend,int(p.required),m.manifest_sha256))
                self.db.commit()
            except Exception: self.db.rollback(); raise
        return job
    def load_manifest(self,domain,scope_id,corpus_id,generation_id):
        row=self.db.execute('SELECT manifest_json FROM generation_manifests WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?',(domain,scope_id,corpus_id,generation_id)).fetchone(); return None if not row else GenerationManifest.model_validate_json(row['manifest_json'])
    def record_receipt(self,m:GenerationManifest,r:ProjectionReceipt):
        spec=next((p for p in m.enabled_projections if p.backend==r.backend),None)
        if spec is None: raise ReceiptMismatch('receipt backend is not enabled by manifest')
        expected=(m.generation_id,m.domain,m.scope_id,m.corpus_id,m.manifest_sha256,m.membership_sha256,len(m.membership),spec.fingerprint)
        actual=(r.generation_id,r.domain,r.scope_id,r.corpus_id,r.manifest_sha256,r.membership_sha256,r.member_count,r.fingerprint)
        if actual!=expected or not r.visibility_verified: raise ReceiptMismatch('receipt generation/scope/hash/count/fingerprint/visibility mismatch')
        with self.store.writer_lock():
            try:
                self.db.execute('BEGIN IMMEDIATE')
                existing=self.db.execute('SELECT receipt_json FROM projection_receipts WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=? AND backend=?',(m.domain,m.scope_id,m.corpus_id,m.generation_id,r.backend)).fetchone()
                receipt_json=canonical_json(r.model_dump(mode='json'))
                if existing and existing['receipt_json']!=receipt_json: raise ReceiptMismatch('verified projection receipt is immutable')
                self.db.execute("INSERT OR IGNORE INTO projection_receipts(domain,scope_id,corpus_id,generation_id,backend,manifest_sha256,membership_sha256,member_count,fingerprint,artifact_sha256,visibility_verified,sentinel,receipt_json,verified_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",(m.domain,m.scope_id,m.corpus_id,m.generation_id,r.backend,r.manifest_sha256,r.membership_sha256,r.member_count,r.fingerprint,r.artifact_sha256,1,r.sentinel,receipt_json))
                self.db.execute("UPDATE projection_jobs SET status='verified',completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),error_code=NULL WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=? AND backend=?",(m.domain,m.scope_id,m.corpus_id,m.generation_id,r.backend)); self.db.commit()
            except Exception: self.db.rollback(); raise
    def all_verified(self,m):
        rows={r['backend'] for r in self.db.execute("SELECT backend FROM projection_jobs WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=? AND status='verified'",(m.domain,m.scope_id,m.corpus_id,m.generation_id))}
        return rows=={p.backend for p in m.enabled_projections}
    def mark_ready(self,m):
        if not self.all_verified(m): raise PublicationNotReady('all enabled projections must verify before ready')
        with self.store.writer_lock(): self.db.execute("UPDATE generation_manifests SET state='ready',ready_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=? AND state='building'",(m.domain,m.scope_id,m.corpus_id,m.generation_id))
    def activate(self,m):
        if self.state(m) not in {'ready','active'}: raise PublicationNotReady('generation must be ready before activation')
        with self.store.writer_lock():
            try:
                self.db.execute('BEGIN IMMEDIATE')
                previous=self.db.execute('SELECT generation_id FROM active_generations WHERE domain=? AND scope_id=? AND corpus_id=?',(m.domain,m.scope_id,m.corpus_id)).fetchone()
                if previous and previous['generation_id']!=m.generation_id: self.db.execute('UPDATE snapshots SET active=0 WHERE domain=? AND scope_id=? AND snapshot_id=?',(m.domain,m.scope_id,previous['generation_id']))
                self.db.execute('UPDATE snapshots SET active=1 WHERE domain=? AND scope_id=? AND snapshot_id=?',(m.domain,m.scope_id,m.generation_id))
                self.db.execute("INSERT INTO active_generations(domain,scope_id,corpus_id,generation_id,manifest_sha256,updated_at) VALUES(?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(domain,scope_id,corpus_id) DO UPDATE SET generation_id=excluded.generation_id,manifest_sha256=excluded.manifest_sha256,updated_at=excluded.updated_at",(m.domain,m.scope_id,m.corpus_id,m.generation_id,m.manifest_sha256))
                self.db.execute("UPDATE generation_manifests SET state='active',activated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?",(m.domain,m.scope_id,m.corpus_id,m.generation_id))
                self.db.execute("UPDATE publication_jobs SET status='activated' WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?",(m.domain,m.scope_id,m.corpus_id,m.generation_id)); self.db.commit()
            except Exception: self.db.rollback(); raise
    def acknowledge(self,m):
        with self.store.writer_lock(): self.db.execute("UPDATE publication_jobs SET status='completed',completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?",(m.domain,m.scope_id,m.corpus_id,m.generation_id))
    def fail(self,m,reason):
        with self.store.writer_lock():
            self.db.execute("UPDATE generation_manifests SET state='failed',failed_reason=? WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=? AND state!='active'",(reason,m.domain,m.scope_id,m.corpus_id,m.generation_id)); self.db.execute("UPDATE publication_jobs SET status='failed',error_code=?,completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?",(reason,m.domain,m.scope_id,m.corpus_id,m.generation_id))
    def state(self,m):
        row=self.db.execute('SELECT state FROM generation_manifests WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?',(m.domain,m.scope_id,m.corpus_id,m.generation_id)).fetchone(); return None if not row else row['state']
    def active_generation(self,domain,scope_id,corpus_id):
        row=self.db.execute('SELECT generation_id,manifest_sha256 FROM active_generations WHERE domain=? AND scope_id=? AND corpus_id=?',(domain,scope_id,corpus_id)).fetchone(); return None if not row else dict(row)
    def recover(self,domain,scope_id,corpus_id):
        active=self.active_generation(domain,scope_id,corpus_id)
        if active:
            m=self.load_manifest(domain,scope_id,corpus_id,active['generation_id'])
            if m:
                with self.store.writer_lock():
                    self.db.execute("UPDATE generation_manifests SET state='active' WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?",(domain,scope_id,corpus_id,m.generation_id)); self.db.execute("UPDATE publication_jobs SET status='completed',completed_at=COALESCE(completed_at,strftime('%Y-%m-%dT%H:%M:%fZ','now')) WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?",(domain,scope_id,corpus_id,m.generation_id))
        for row in self.db.execute("SELECT generation_id,state FROM generation_manifests WHERE domain=? AND scope_id=? AND corpus_id=? AND state IN('building','ready') ORDER BY created_at",(domain,scope_id,corpus_id)).fetchall():
            m=self.load_manifest(domain,scope_id,corpus_id,row['generation_id'])
            if m and self.all_verified(m):
                if row['state']=='building': self.mark_ready(m)
                self.activate(m); self.acknowledge(m)
        return self.active_generation(domain,scope_id,corpus_id)
    def member(self,m,kind,euid,ruid): return self.db.execute('SELECT 1 FROM snapshot_membership WHERE domain=? AND scope_id=? AND snapshot_id=? AND evidence_kind=? AND evidence_uid=? AND revision_uid=?',(m.domain,m.scope_id,m.generation_id,kind,euid,ruid)).fetchone() is not None
    def withdrawn(self,m,kind,euid):
        if kind=='object': return self.db.execute("SELECT 1 FROM object_revisions WHERE domain=? AND scope_id=? AND object_uid=? AND lifecycle_state IN('revoked','deleted') LIMIT 1",(m.domain,m.scope_id,euid)).fetchone() is not None
        if kind=='relation': return self.db.execute("SELECT 1 FROM relation_revisions WHERE domain=? AND scope_id=? AND relation_uid=? AND lifecycle_state IN('revoked','deleted') LIMIT 1",(m.domain,m.scope_id,euid)).fetchone() is not None
        row=self.db.execute('SELECT object_uid FROM chunks WHERE domain=? AND scope_id=? AND chunk_uid=?',(m.domain,m.scope_id,euid)).fetchone(); return False if not row else self.withdrawn(m,'object',row['object_uid'])

@dataclass
class SnapshotHandle:
    manager:'SnapshotManager'; manifest:GenerationManifest; released:bool=False
    @property
    def snapshot(self): return SnapshotRef(domain=self.manifest.domain,scope_id=self.manifest.scope_id,snapshot_id=self.manifest.generation_id,manifest_sha256=self.manifest.manifest_sha256)
    def release(self):
        if not self.released: self.released=True; self.manager._release(self.manifest.generation_id)
    def __enter__(self): return self
    def __exit__(self,*a): self.release()
    def _live(self):
        if self.released: raise RuntimeError('snapshot handle is released')
    def get_revision(self,revision_uid):
        self._live(); r=self.manager.store.get_revision(self.manifest.domain,self.manifest.scope_id,revision_uid)
        if not r or not self.manager.catalog.member(self.manifest,r['kind'],r['evidence_uid'],revision_uid): return None
        if self.manager.catalog.withdrawn(self.manifest,r['kind'],r['evidence_uid']): raise EvidenceWithdrawn('evidence is withdrawn by live policy/lifecycle overlay')
        return r

class SnapshotManager:
    def __init__(self,store): self.store=store; self.catalog=SnapshotCatalog(store); self._pins={}
    def pin_active(self,scope:ResolvedScope):
        row=self.catalog.active_generation(scope.domain,scope.scope_id,scope.corpus_id)
        if not row: raise PublicationNotReady('no active generation')
        m=self.catalog.load_manifest(scope.domain,scope.scope_id,scope.corpus_id,row['generation_id']); self._pins[m.generation_id]=self._pins.get(m.generation_id,0)+1; return SnapshotHandle(self,m)
    def _release(self,gid): self._pins[gid]=max(0,self._pins.get(gid,0)-1)
    def pin_count(self,gid): return self._pins.get(gid,0)
