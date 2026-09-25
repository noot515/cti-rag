"""Scope-complete retrieval caches with independent revocation invalidation."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import hashlib,json,sqlite3,time
from pathlib import Path
from typing import Optional,Tuple

class CacheState(str,Enum):
    MISS="miss";VALUE="value";EMPTY="empty";FAILED="failed"

@dataclass(frozen=True)
class CacheIdentity:
    principal_security_namespace:str
    effective_scope_hash:str
    policy_epoch:str
    normalized_query:str
    exact_identifiers:Tuple[str,...]
    snapshot_id:str
    temporal_mode:str
    temporal_cutoff:Optional[str]
    plan_fingerprint:str
    config_fingerprint:str
    model_fingerprints:Tuple[str,...]
    locale:str
    cache_kind:str
    def __post_init__(self):
        required=(self.principal_security_namespace,self.effective_scope_hash,self.policy_epoch,self.normalized_query,self.snapshot_id,self.temporal_mode,self.plan_fingerprint,self.config_fingerprint,self.locale,self.cache_kind)
        if any(not str(v).strip() for v in required):raise ValueError("cache identity fields required")
    @property
    def key(self):
        body={
            "principal_security_namespace":self.principal_security_namespace,
            "effective_scope_hash":self.effective_scope_hash,"policy_epoch":self.policy_epoch,
            "normalized_query":self.normalized_query,"exact_identifiers":tuple(sorted(self.exact_identifiers)),
            "snapshot_id":self.snapshot_id,"temporal_mode":self.temporal_mode,"temporal_cutoff":self.temporal_cutoff,
            "plan_fingerprint":self.plan_fingerprint,"config_fingerprint":self.config_fingerprint,
            "model_fingerprints":tuple(sorted(self.model_fingerprints)),"locale":self.locale,"cache_kind":self.cache_kind,
        }
        raw=json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()

@dataclass(frozen=True)
class CacheLookup:
    state:CacheState
    payload:object|None=None
    reason:Optional[str]=None

class SQLiteScopedCache:
    def __init__(self,path,*,clock=time.time):
        self.path=str(Path(path));Path(self.path).parent.mkdir(parents=True,exist_ok=True);self.clock=clock;self._initialize()
    def _connect(self):return sqlite3.connect(self.path)
    def _initialize(self):
        conn=self._connect()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS cache_entries (cache_key TEXT PRIMARY KEY, namespace TEXT NOT NULL, state TEXT NOT NULL, payload_json TEXT NULL, reason TEXT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS cache_targets (cache_key TEXT NOT NULL, target_uid TEXT NOT NULL, PRIMARY KEY(cache_key,target_uid))")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_targets_uid ON cache_targets(target_uid)")
            conn.commit()
        finally:conn.close()
    def put(self,identity,payload,*,ttl_seconds,target_uids=(),state=CacheState.VALUE,reason=None):
        if ttl_seconds<=0:raise ValueError("cache TTL must be positive")
        if state==CacheState.MISS:raise ValueError("MISS cannot be persisted")
        key=identity.key;now=float(self.clock());encoded=None if payload is None else json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False)
        conn=self._connect()
        try:
            conn.execute("INSERT OR REPLACE INTO cache_entries(cache_key,namespace,state,payload_json,reason,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",(key,identity.principal_security_namespace,state.value,encoded,reason,now,now+ttl_seconds))
            conn.execute("DELETE FROM cache_targets WHERE cache_key=?",(key,))
            for uid in tuple(dict.fromkeys(str(v) for v in target_uids if str(v).strip())):conn.execute("INSERT INTO cache_targets(cache_key,target_uid) VALUES(?,?)",(key,uid))
            conn.commit()
        finally:conn.close()
        return key
    def put_empty(self,identity,*,ttl_seconds,target_uids=()):return self.put(identity,None,ttl_seconds=ttl_seconds,target_uids=target_uids,state=CacheState.EMPTY)
    def put_failed(self,identity,reason,*,ttl_seconds):
        if not str(reason).strip():raise ValueError("failed cache entry requires reason")
        return self.put(identity,None,ttl_seconds=ttl_seconds,state=CacheState.FAILED,reason=str(reason))
    def get(self,identity,*,revoked=None):
        key=identity.key;now=float(self.clock());conn=self._connect()
        try:
            row=conn.execute("SELECT state,payload_json,reason,expires_at FROM cache_entries WHERE cache_key=?",(key,)).fetchone()
            if row is None:return CacheLookup(CacheState.MISS)
            if float(row[3])<=now:
                conn.execute("DELETE FROM cache_targets WHERE cache_key=?",(key,));conn.execute("DELETE FROM cache_entries WHERE cache_key=?",(key,));conn.commit();return CacheLookup(CacheState.MISS)
            targets=tuple(v[0] for v in conn.execute("SELECT target_uid FROM cache_targets WHERE cache_key=?",(key,)).fetchall())
            if revoked is not None and any(revoked(uid) for uid in targets):
                conn.execute("DELETE FROM cache_targets WHERE cache_key=?",(key,));conn.execute("DELETE FROM cache_entries WHERE cache_key=?",(key,));conn.commit();return CacheLookup(CacheState.MISS,reason="revoked")
            state=CacheState(row[0]);payload=None if row[1] is None else json.loads(row[1]);return CacheLookup(state,payload,row[2])
        finally:conn.close()
    def invalidate_target(self,target_uid):
        conn=self._connect()
        try:
            keys=[r[0] for r in conn.execute("SELECT cache_key FROM cache_targets WHERE target_uid=?",(target_uid,)).fetchall()]
            for key in keys:
                conn.execute("DELETE FROM cache_targets WHERE cache_key=?",(key,));conn.execute("DELETE FROM cache_entries WHERE cache_key=?",(key,))
            conn.commit();return len(keys)
        finally:conn.close()
    def count(self):
        conn=self._connect()
        try:return int(conn.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0])
        finally:conn.close()

class CacheBundle:
    """Physically separate public/private and query/embedding stores."""
    def __init__(self,root,*,clock=time.time):
        root=Path(root);root.mkdir(parents=True,exist_ok=True)
        self._stores={
            ("query",False):SQLiteScopedCache(root/"query-public.sqlite",clock=clock),
            ("query",True):SQLiteScopedCache(root/"query-private.sqlite",clock=clock),
            ("embedding",False):SQLiteScopedCache(root/"embedding-public.sqlite",clock=clock),
            ("embedding",True):SQLiteScopedCache(root/"embedding-private.sqlite",clock=clock),
        }
    def store(self,cache_kind,is_private):
        key=(str(cache_kind),bool(is_private))
        if key not in self._stores:raise KeyError(key)
        return self._stores[key]
