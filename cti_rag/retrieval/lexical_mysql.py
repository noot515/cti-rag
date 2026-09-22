"""Production-candidate persistent MySQL 8 FULLTEXT lexical adapter.

This adapter deliberately reuses an already configured legacy manager engine/pool and
does not create credentials or import SQLAlchemy. It is implemented from the Phase 0
MySQL capability decision, but real-service acceptance remains a separate integration gate.
"""
from __future__ import annotations
from datetime import datetime,timezone
import json,re
from cti_rag.contracts import PassageHit,ProvenanceRef,ScoreDirection,ScoreMetadata,TemporalMode,locator_from_dict,namespaced_uid,sha256_hex
from cti_rag.ports import BackendCapabilities,ChannelResult,ChannelStatus,ProjectionBuildRequest
from cti_rag.snapshots import ProjectionGeneration,ProjectionPayload

def _iso(v): return None if v is None else v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
def _dt(v): return None if v is None else datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(timezone.utc)

class MySQLFullTextLexicalIndex:
    kind="lexical"
    capabilities=BackendCapabilities(
        supported_filters=frozenset({"tenant","domain","access_label","source","temporal"}),
        temporal_modes=frozenset({TemporalMode.CURRENT,TemporalMode.HISTORICAL_PUBLIC,TemporalMode.HISTORICAL_SYSTEM_REPLAY}),
        snapshot_support=True,requires_snapshot=True,pagination=False,cancellation=False,max_batch_size=1000,
        score_direction=ScoreDirection.HIGHER_IS_BETTER,
    )
    def __init__(self,manager,catalog):
        self.manager=manager; self.catalog=catalog; self.initialize()
    def connect(self): return self.manager.engine.raw_connection()
    def initialize(self):
        conn=self.connect(); cur=conn.cursor()
        try:
            cur.execute("""CREATE TABLE IF NOT EXISTS evidence_lexical_generations (
                generation_id VARCHAR(160) PRIMARY KEY, checksum VARCHAR(64) NOT NULL, analyzer_version VARCHAR(128) NOT NULL,
                revision_set_json JSON NOT NULL, representation_versions_json JSON NOT NULL, capabilities_json JSON NOT NULL,
                quarantined_count INT NOT NULL, doc_count BIGINT NOT NULL, created_at VARCHAR(40) NOT NULL
            ) ENGINE=InnoDB""")
            cur.execute("""CREATE TABLE IF NOT EXISTS evidence_lexical_documents (
                generation_id VARCHAR(160) NOT NULL, passage_uid VARCHAR(160) NOT NULL, revision_uid VARCHAR(160) NOT NULL,
                object_uid VARCHAR(160) NOT NULL, namespace VARCHAR(64) NOT NULL, object_type VARCHAR(128) NOT NULL,
                canonical_id VARCHAR(255) NOT NULL, domain VARCHAR(64) NOT NULL, source_id VARCHAR(160) NOT NULL,
                tenant_id VARCHAR(160) NOT NULL, access_label VARCHAR(32) NOT NULL, available_at VARCHAR(40) NULL,
                valid_from VARCHAR(40) NULL, valid_to VARCHAR(40) NULL, locator_json TEXT NOT NULL, analyzer_version VARCHAR(128) NOT NULL,
                original_text LONGTEXT NOT NULL, normalized_text LONGTEXT NOT NULL, context_prefix TEXT NOT NULL,
                PRIMARY KEY (generation_id,passage_uid),
                KEY evidence_lexical_scope (generation_id,tenant_id,domain,access_label,source_id),
                FULLTEXT KEY evidence_lexical_text (normalized_text,context_prefix)
            ) ENGINE=InnoDB""")
            conn.commit()
        finally:cur.close(); conn.close()
    def _identity(self,d):
        return {"passage_uid":d.passage_uid,"revision_uid":d.revision_uid,"object_uid":d.object_uid,"namespace":d.namespace,"object_type":d.object_type,"canonical_id":d.canonical_id,"domain":d.domain,"source_id":d.source_id,"tenant_id":d.tenant_id,"access_label":d.access_label.value,"available_at":_iso(d.available_at),"valid_from":_iso(d.valid_from),"valid_to":_iso(d.valid_to),"locator_json":d.locator_json,"original_text":d.original_text,"normalized_text":d.normalized_text,"context_prefix":d.context_prefix,"analyzer_version":d.analyzer_version}
    def build(self,request:ProjectionBuildRequest,documents):
        if request.kind!="lexical":raise ValueError("lexical builder received non-lexical request")
        docs=tuple(sorted(documents,key=lambda d:d.passage_uid)); revisions=tuple(sorted(request.revision_uids)); allowed=set(revisions)
        if any(d.revision_uid not in allowed for d in docs):raise ValueError("document revision outside projection revision set")
        analyzers=tuple(sorted({d.analyzer_version for d in docs}))
        if len(analyzers)!=1:raise ValueError("one lexical generation requires one analyzer version")
        checksum=sha256_hex({"generation_id":request.generation_id,"documents":[self._identity(d) for d in docs],"revision_uids":revisions,"representation_versions":request.representation_versions})
        conn=self.connect(); cur=conn.cursor()
        try:
            cur.execute("SELECT checksum FROM evidence_lexical_generations WHERE generation_id=%s",(request.generation_id,)); row=cur.fetchone()
            if row:
                if row[0]!=checksum:raise ValueError("immutable lexical generation already exists with different checksum")
                return self._generation(request.generation_id)
            conn.begin()
            for d in docs:
                cur.execute("""INSERT INTO evidence_lexical_documents (
                    generation_id,passage_uid,revision_uid,object_uid,namespace,object_type,canonical_id,domain,source_id,tenant_id,
                    access_label,available_at,valid_from,valid_to,locator_json,analyzer_version,original_text,normalized_text,context_prefix
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(
                    request.generation_id,d.passage_uid,d.revision_uid,d.object_uid,d.namespace,d.object_type,d.canonical_id,d.domain,d.source_id,d.tenant_id,
                    d.access_label.value,_iso(d.available_at),_iso(d.valid_from),_iso(d.valid_to),d.locator_json,d.analyzer_version,d.original_text,d.normalized_text,d.context_prefix,
                ))
            cur.execute("INSERT INTO evidence_lexical_generations VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",(
                request.generation_id,checksum,analyzers[0],json.dumps(revisions),json.dumps(tuple(request.representation_versions)),json.dumps(tuple(request.supported_query_capabilities)),
                request.quarantined_count,len(docs),_iso(datetime.now(timezone.utc)),
            )); conn.commit()
        except Exception:conn.rollback(); raise
        finally:cur.close(); conn.close()
        return self._generation(request.generation_id)
    def _generation(self,generation_id):
        conn=self.connect(); cur=conn.cursor()
        try:
            cur.execute("SELECT checksum,analyzer_version,revision_set_json,representation_versions_json,capabilities_json,quarantined_count,doc_count,created_at FROM evidence_lexical_generations WHERE generation_id=%s",(generation_id,)); row=cur.fetchone()
            if row is None:return None
            revisions=tuple(json.loads(row[2] if isinstance(row[2],str) else json.dumps(row[2])))
            reps=tuple(json.loads(row[3] if isinstance(row[3],str) else json.dumps(row[3])))
            caps=tuple(json.loads(row[4] if isinstance(row[4],str) else json.dumps(row[4])))
            cur.execute("SELECT passage_uid,revision_uid,locator_json,original_text FROM evidence_lexical_documents WHERE generation_id=%s ORDER BY passage_uid",(generation_id,)); docs=cur.fetchall()
            payloads=tuple(ProjectionPayload(p,r,l,sha256_hex(t.encode("utf-8")),t) for p,r,l,t in docs)
            return ProjectionGeneration(generation_id,"lexical",revisions,reps,row[0],True,len(docs)==int(row[6]),all(r in set(revisions) for _,r,_,_ in docs),int(row[5]),caps,_dt(row[7]),payloads)
        finally:cur.close(); conn.close()
    def validate(self,generation):
        current=self._generation(generation.generation_id); return bool(current and current.checksum==generation.checksum and current.ready and current.visible and current.referential_integrity)
    def cleanup(self,generation_id):
        conn=self.connect(); cur=conn.cursor()
        try:
            conn.begin(); cur.execute("DELETE FROM evidence_lexical_documents WHERE generation_id=%s",(generation_id,)); cur.execute("DELETE FROM evidence_lexical_generations WHERE generation_id=%s",(generation_id,)); conn.commit()
        except Exception:conn.rollback(); raise
        finally:cur.close(); conn.close()
    async def search(self,request):
        if request.snapshot is None:return ChannelResult(ChannelStatus.REJECTED,reason="lexical backend requires pinned snapshot")
        generation_id=self.catalog.generation_for_manifest(request.snapshot.manifest_id,"lexical")
        if generation_id is None:return ChannelResult(ChannelStatus.REJECTED,reason="snapshot has no lexical generation")
        clauses=["generation_id=%s"]; params=[generation_id]
        tenants=tuple(dict.fromkeys((request.scope.tenant_id,"public"))); clauses.append("tenant_id IN ("+",".join("%s" for _ in tenants)+")"); params.extend(tenants)
        clauses.append("domain IN ("+",".join("%s" for _ in request.scope.domains)+")"); params.extend(request.scope.domains)
        labels=tuple(v.value for v in request.scope.access_labels); clauses.append("access_label IN ("+",".join("%s" for _ in labels)+")"); params.extend(labels)
        if request.scope.source_ids:
            clauses.append("source_id IN ("+",".join("%s" for _ in request.scope.source_ids)+")"); params.extend(request.scope.source_ids)
        now=_iso(datetime.now(timezone.utc))
        if request.temporal.mode==TemporalMode.HISTORICAL_PUBLIC:
            if not request.temporal.cutoff_iso:return ChannelResult(ChannelStatus.REJECTED,reason="historical public search requires cutoff")
            cutoff=_iso(datetime.fromisoformat(request.temporal.cutoff_iso.replace("Z","+00:00"))); clauses.append("available_at IS NOT NULL AND available_at<=%s"); params.append(cutoff)
        else:
            clauses.append("(available_at IS NULL OR available_at<=%s)"); params.append(now)
        revoked=tuple(self.catalog.revoked_uids())
        if revoked:
            marks=",".join("%s" for _ in revoked); clauses.extend((f"revision_uid NOT IN ({marks})",f"passage_uid NOT IN ({marks})",f"object_uid NOT IN ({marks})"))
            params.extend(revoked); params.extend(revoked); params.extend(revoked)
        score="MATCH(normalized_text,context_prefix) AGAINST (%s IN NATURAL LANGUAGE MODE)"
        limit=min(request.budget.total,request.budget.lexical or request.budget.total)
        sql=f"""SELECT passage_uid,revision_uid,locator_json,original_text,{score} AS score
                FROM evidence_lexical_documents
                WHERE {score}>0 AND """+" AND ".join(clauses)+" ORDER BY score DESC,passage_uid ASC LIMIT %s"
        params=[request.query,request.query]+params+[limit]
        conn=self.connect(); cur=conn.cursor()
        try:cur.execute(sql,tuple(params)); rows=cur.fetchall()
        finally:cur.close(); conn.close()
        if not rows:return ChannelResult(ChannelStatus.EMPTY,reason="no authorized lexical matches")
        hits=[]
        for rank,(passage_uid,revision_uid,locator_json,text,score_value) in enumerate(rows,1):
            locator=locator_from_dict(json.loads(locator_json)); hit_id=namespaced_uid("hit","lexical.search",{"manifest":request.snapshot.manifest_id,"passage_uid":passage_uid,"query":request.query})
            hits.append(PassageHit(hit_id,passage_uid,revision_uid,ProvenanceRef(revision_uid,locator),text,(ScoreMetadata("lexical",float(score_value),ScoreDirection.HIGHER_IS_BETTER,rank,"mysql-fulltext"),)))
        return ChannelResult(ChannelStatus.OK,tuple(hits))
