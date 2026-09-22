"""Persistent exact canonical identifier index with revision-aware selection."""
from __future__ import annotations
from datetime import datetime,timezone
import json,sqlite3
from pathlib import Path
from cti_rag.contracts import TemporalMode,sha256_hex
from cti_rag.identifiers import default_identifier_registry
from cti_rag.ports import ProjectionBuildRequest
from cti_rag.retrieval.models import ExactLookupResult,ExactLookupStatus,ExactRecord
from cti_rag.snapshots import ProjectionGeneration,ProjectionPayload

def _iso(v): return None if v is None else v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
def _dt(v): return None if v is None else datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(timezone.utc)

class PersistentExactIndex:
    kind="exact"
    def __init__(self,connection_factory,dialect,catalog,identifier_registry=None):
        self._connection_factory=connection_factory; self.dialect=dialect; self.catalog=catalog; self.identifiers=identifier_registry or default_identifier_registry(); self.initialize()
    @classmethod
    def sqlite(cls,path,catalog,identifier_registry=None):
        path=str(Path(path)); return cls(lambda:sqlite3.connect(path),"sqlite",catalog,identifier_registry)
    @classmethod
    def from_existing_manager(cls,manager,catalog,identifier_registry=None):
        return cls(manager.engine.raw_connection,getattr(manager.engine.dialect,"name","mysql"),catalog,identifier_registry)
    def _sql(self,sql): return sql if self.dialect=="sqlite" else sql.replace("?","%s")
    def connect(self): return self._connection_factory()
    def initialize(self):
        conn=self.connect(); cur=conn.cursor()
        try:
            cur.execute("""CREATE TABLE IF NOT EXISTS exact_generations (
                generation_id VARCHAR(160) PRIMARY KEY, checksum VARCHAR(64) NOT NULL, revision_set_json TEXT NOT NULL,
                representation_versions_json TEXT NOT NULL, capabilities_json TEXT NOT NULL, quarantined_count INTEGER NOT NULL,
                record_count INTEGER NOT NULL, created_at VARCHAR(40) NOT NULL
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS exact_records (
                generation_id VARCHAR(160) NOT NULL, revision_uid VARCHAR(160) NOT NULL, object_uid VARCHAR(160) NOT NULL,
                namespace VARCHAR(64) NOT NULL, object_type VARCHAR(128) NOT NULL, canonical_id VARCHAR(255) NOT NULL,
                domain VARCHAR(64) NOT NULL, source_id VARCHAR(160) NOT NULL, tenant_id VARCHAR(160) NOT NULL,
                access_label VARCHAR(32) NOT NULL, available_at VARCHAR(40) NULL, valid_from VARCHAR(40) NULL, valid_to VARCHAR(40) NULL,
                locator_json TEXT NOT NULL, original_text TEXT NOT NULL,
                PRIMARY KEY (generation_id, revision_uid, namespace, canonical_id)
            )""")
            cur.execute("CREATE INDEX IF NOT EXISTS exact_lookup_idx ON exact_records (generation_id,namespace,canonical_id,object_type)")
            conn.commit()
        finally: cur.close(); conn.close()
    def _identity(self,r):
        return {"revision_uid":r.revision_uid,"object_uid":r.object_uid,"namespace":r.namespace,"object_type":r.object_type,"canonical_id":r.canonical_id,"domain":r.domain,"source_id":r.source_id,"tenant_id":r.tenant_id,"access_label":r.access_label.value,"available_at":_iso(r.available_at),"valid_from":_iso(r.valid_from),"valid_to":_iso(r.valid_to),"locator_json":r.locator_json,"original_text":r.original_text}
    def build(self,request:ProjectionBuildRequest,records):
        if request.kind!="exact": raise ValueError("exact builder received non-exact request")
        records=tuple(sorted(records,key=lambda r:(r.namespace,r.canonical_id,r.object_uid,r.revision_uid))); revisions=tuple(sorted(request.revision_uids)); allowed=set(revisions)
        if any(r.revision_uid not in allowed for r in records): raise ValueError("exact record revision outside projection revision set")
        checksum=sha256_hex({"generation_id":request.generation_id,"records":[self._identity(r) for r in records],"revision_uids":revisions,"representation_versions":request.representation_versions})
        conn=self.connect(); cur=conn.cursor()
        try:
            cur.execute(self._sql("SELECT checksum FROM exact_generations WHERE generation_id=?"),(request.generation_id,)); row=cur.fetchone()
            if row:
                if row[0]!=checksum: raise ValueError("immutable exact generation already exists with different checksum")
                return self._generation(request.generation_id)
            if self.dialect=="sqlite": cur.execute("BEGIN IMMEDIATE")
            for r in records:
                cur.execute(self._sql("""INSERT INTO exact_records (
                    generation_id,revision_uid,object_uid,namespace,object_type,canonical_id,domain,source_id,tenant_id,access_label,
                    available_at,valid_from,valid_to,locator_json,original_text
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""),(request.generation_id,r.revision_uid,r.object_uid,r.namespace,r.object_type,r.canonical_id,r.domain,r.source_id,r.tenant_id,r.access_label.value,_iso(r.available_at),_iso(r.valid_from),_iso(r.valid_to),r.locator_json,r.original_text))
            created=_iso(datetime.now(timezone.utc))
            cur.execute(self._sql("INSERT INTO exact_generations VALUES (?,?,?,?,?,?,?,?)"),(request.generation_id,checksum,json.dumps(revisions),json.dumps(tuple(request.representation_versions)),json.dumps(tuple(request.supported_query_capabilities)),request.quarantined_count,len(records),created))
            conn.commit()
        except Exception: conn.rollback(); raise
        finally: cur.close(); conn.close()
        return self._generation(request.generation_id)
    def _generation(self,generation_id):
        conn=self.connect(); cur=conn.cursor()
        try:
            cur.execute(self._sql("SELECT checksum,revision_set_json,representation_versions_json,capabilities_json,quarantined_count,record_count,created_at FROM exact_generations WHERE generation_id=?"),(generation_id,)); row=cur.fetchone()
            if row is None:return None
            cur.execute(self._sql("SELECT revision_uid,locator_json,original_text FROM exact_records WHERE generation_id=? ORDER BY namespace,canonical_id,revision_uid"),(generation_id,)); recs=cur.fetchall()
            visible=len(recs)==int(row[5]); revisions=tuple(json.loads(row[1])); allowed=set(revisions)
            payloads=tuple(ProjectionPayload(f"exact:{rev}",rev,loc,sha256_hex(text.encode("utf-8")),text) for rev,loc,text in recs)
            return ProjectionGeneration(generation_id,"exact",revisions,tuple(json.loads(row[2])),row[0],True,visible,all(r in allowed for r,_,_ in recs),int(row[4]),tuple(json.loads(row[3])),_dt(row[6]),payloads)
        finally:cur.close(); conn.close()
    def validate(self,generation):
        current=self._generation(generation.generation_id)
        return bool(current and current.checksum==generation.checksum and current.ready and current.visible and current.referential_integrity)
    def cleanup(self,generation_id):
        conn=self.connect(); cur=conn.cursor()
        try:
            if self.dialect=="sqlite":cur.execute("BEGIN IMMEDIATE")
            cur.execute(self._sql("DELETE FROM exact_records WHERE generation_id=?"),(generation_id,)); cur.execute(self._sql("DELETE FROM exact_generations WHERE generation_id=?"),(generation_id,)); conn.commit()
        except Exception:conn.rollback(); raise
        finally:cur.close(); conn.close()
    def lookup(self,request):
        if request.snapshot is None:return ExactLookupResult(ExactLookupStatus.REJECTED,reason="exact lookup requires pinned snapshot")
        parsed=self.identifiers.parse_all(request.raw_identifier,request.namespace)
        if not parsed:return ExactLookupResult(ExactLookupStatus.INVALID,reason="identifier did not match a registered canonical grammar")
        if len(parsed)>1:return ExactLookupResult(ExactLookupStatus.AMBIGUOUS,reason="identifier matches multiple namespaces")
        identifier=parsed[0]
        if request.object_type and request.object_type!=identifier.object_type:return ExactLookupResult(ExactLookupStatus.INVALID,reason="identifier namespace/object type mismatch")
        generation_id=self.catalog.generation_for_manifest(request.snapshot.manifest_id,"exact")
        if generation_id is None:return ExactLookupResult(ExactLookupStatus.REJECTED,reason="snapshot has no exact generation")
        clauses=["generation_id=?","namespace=?","canonical_id=?","object_type=?"]; params=[generation_id,identifier.namespace,identifier.canonical,identifier.object_type]
        tenants=tuple(dict.fromkeys((request.scope.tenant_id,"public"))); clauses.append("tenant_id IN ("+",".join("?" for _ in tenants)+")"); params.extend(tenants)
        clauses.append("domain IN ("+",".join("?" for _ in request.scope.domains)+")"); params.extend(request.scope.domains)
        clauses.append("access_label IN ("+",".join("?" for _ in request.scope.access_labels)+")"); params.extend(v.value for v in request.scope.access_labels)
        if request.scope.source_ids:
            clauses.append("source_id IN ("+",".join("?" for _ in request.scope.source_ids)+")"); params.extend(request.scope.source_ids)
        now=datetime.now(timezone.utc)
        if request.temporal.mode==TemporalMode.HISTORICAL_PUBLIC:
            if not request.temporal.cutoff_iso:return ExactLookupResult(ExactLookupStatus.REJECTED,reason="historical public exact lookup requires cutoff")
            cutoff=_iso(datetime.fromisoformat(request.temporal.cutoff_iso.replace("Z","+00:00"))); clauses.append("available_at IS NOT NULL AND available_at<=?"); params.append(cutoff)
        else:
            clauses.append("(available_at IS NULL OR available_at<=?)"); params.append(_iso(now))
        if request.valid_at is not None:
            point=_iso(request.valid_at); clauses.append("(valid_from IS NULL OR valid_from<=?) AND (valid_to IS NULL OR valid_to>?)"); params.extend((point,point))
        revoked=tuple(self.catalog.revoked_uids())
        if revoked:
            marks=",".join("?" for _ in revoked)
            clauses.extend((f"revision_uid NOT IN ({marks})",f"object_uid NOT IN ({marks})")); params.extend(revoked); params.extend(revoked)
        sql="SELECT revision_uid,object_uid,namespace,object_type,canonical_id,domain,source_id,tenant_id,access_label,available_at,valid_from,valid_to,locator_json,original_text FROM exact_records WHERE "+" AND ".join(clauses)
        conn=self.connect(); cur=conn.cursor()
        try:cur.execute(self._sql(sql),tuple(params)); rows=cur.fetchall()
        finally:cur.close(); conn.close()
        if not rows:return ExactLookupResult(ExactLookupStatus.NOT_FOUND)
        records=tuple(ExactRecord(r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],__import__("cti_rag.contracts",fromlist=["AccessLabel"]).AccessLabel(r[8]),_dt(r[9]),_dt(r[10]),_dt(r[11]),r[12],r[13]) for r in rows)
        objects={r.object_uid for r in records}
        if len(objects)>1:return ExactLookupResult(ExactLookupStatus.AMBIGUOUS,records,reason="canonical identifier maps to multiple logical objects in authorized scope")
        eligible=sorted(records,key=lambda r:((_iso(r.available_at) or ""),r.revision_uid),reverse=True)
        return ExactLookupResult(ExactLookupStatus.FOUND,(eligible[0],))
