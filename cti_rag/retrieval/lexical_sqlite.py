"""Persistent independent lexical search using SQLite FTS5 for the local validated profile."""
from __future__ import annotations
from datetime import datetime,timezone
import json,re,sqlite3
from pathlib import Path
from cti_rag.contracts import PassageHit,ProvenanceRef,ScoreDirection,ScoreMetadata,TemporalMode,locator_from_dict,namespaced_uid,sha256_hex
from cti_rag.ports import BackendCapabilities,ChannelResult,ChannelStatus,ProjectionBuildRequest
from cti_rag.retrieval.models import LexicalDocument
from cti_rag.snapshots import ProjectionGeneration,ProjectionPayload

def _iso(v): return None if v is None else v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
def _dt(v): return None if v is None else datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(timezone.utc)
def _safe_match(query):
    tokens=re.findall(r"[\w][\w./:@+\-]*",query,flags=re.UNICODE)
    if not tokens: return None
    return " AND ".join('"'+t.replace('"','""')+'"' for t in tokens)

class SQLiteFTS5LexicalIndex:
    kind="lexical"
    capabilities=BackendCapabilities(
        supported_filters=frozenset({"tenant","domain","access_label","source","temporal"}),
        temporal_modes=frozenset({TemporalMode.CURRENT,TemporalMode.HISTORICAL_PUBLIC,TemporalMode.HISTORICAL_SYSTEM_REPLAY}),
        snapshot_support=True,requires_snapshot=True,pagination=False,cancellation=False,max_batch_size=1000,
        score_direction=ScoreDirection.LOWER_IS_BETTER,
    )
    def __init__(self,path,catalog):
        self.path=str(Path(path)); self.catalog=catalog; self.initialize()
    def connect(self): return sqlite3.connect(self.path)
    def initialize(self):
        conn=self.connect()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS lexical_generations (generation_id TEXT PRIMARY KEY, checksum TEXT NOT NULL, analyzer_version TEXT NOT NULL, revision_set_json TEXT NOT NULL, representation_versions_json TEXT NOT NULL, capabilities_json TEXT NOT NULL, quarantined_count INTEGER NOT NULL, doc_count INTEGER NOT NULL, created_at TEXT NOT NULL)")
            conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS lexical_fts USING fts5(
                generation_id UNINDEXED, passage_uid UNINDEXED, revision_uid UNINDEXED, object_uid UNINDEXED,
                namespace UNINDEXED, object_type UNINDEXED, canonical_id UNINDEXED, domain UNINDEXED,
                source_id UNINDEXED, tenant_id UNINDEXED, access_label UNINDEXED, available_at UNINDEXED,
                valid_from UNINDEXED, valid_to UNINDEXED, locator_json UNINDEXED, analyzer_version UNINDEXED,
                original_text UNINDEXED, normalized_text, context_prefix,
                tokenize='unicode61 remove_diacritics 2'
            )""")
            conn.commit()
        finally: conn.close()
    def _document_identity(self,d):
        return {
            "passage_uid":d.passage_uid,"revision_uid":d.revision_uid,"object_uid":d.object_uid,"namespace":d.namespace,
            "object_type":d.object_type,"canonical_id":d.canonical_id,"domain":d.domain,"source_id":d.source_id,
            "tenant_id":d.tenant_id,"access_label":d.access_label.value,"available_at":_iso(d.available_at),
            "valid_from":_iso(d.valid_from),"valid_to":_iso(d.valid_to),"locator_json":d.locator_json,
            "original_text":d.original_text,"normalized_text":d.normalized_text,"context_prefix":d.context_prefix,
            "analyzer_version":d.analyzer_version,
        }
    def build(self,request:ProjectionBuildRequest,documents):
        if request.kind!="lexical": raise ValueError("lexical builder received non-lexical request")
        docs=tuple(sorted(documents,key=lambda d:d.passage_uid))
        revision_uids=tuple(sorted(request.revision_uids))
        if any(d.revision_uid not in set(revision_uids) for d in docs): raise ValueError("document revision outside projection revision set")
        analyzer_versions=tuple(sorted({d.analyzer_version for d in docs}))
        if len(analyzer_versions)!=1: raise ValueError("one lexical generation requires one analyzer version")
        checksum=sha256_hex({"generation_id":request.generation_id,"documents":[self._document_identity(d) for d in docs],"revision_uids":revision_uids,"representation_versions":request.representation_versions})
        conn=self.connect()
        try:
            row=conn.execute("SELECT checksum FROM lexical_generations WHERE generation_id=?",(request.generation_id,)).fetchone()
            if row:
                if row[0]!=checksum: raise ValueError("immutable lexical generation already exists with different checksum")
                return self._generation(request.generation_id)
            conn.execute("BEGIN IMMEDIATE")
            for d in docs:
                conn.execute("""INSERT INTO lexical_fts (
                    generation_id,passage_uid,revision_uid,object_uid,namespace,object_type,canonical_id,domain,source_id,
                    tenant_id,access_label,available_at,valid_from,valid_to,locator_json,analyzer_version,original_text,normalized_text,context_prefix
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                    request.generation_id,d.passage_uid,d.revision_uid,d.object_uid,d.namespace,d.object_type,d.canonical_id,d.domain,d.source_id,
                    d.tenant_id,d.access_label.value,_iso(d.available_at),_iso(d.valid_from),_iso(d.valid_to),d.locator_json,d.analyzer_version,d.original_text,d.normalized_text,d.context_prefix,
                ))
            created=_iso(datetime.now(timezone.utc))
            conn.execute("INSERT INTO lexical_generations VALUES (?,?,?,?,?,?,?,?,?)",(
                request.generation_id,checksum,analyzer_versions[0],json.dumps(revision_uids),json.dumps(tuple(request.representation_versions)),
                json.dumps(tuple(request.supported_query_capabilities)),request.quarantined_count,len(docs),created,
            ))
            conn.commit()
        except Exception:
            conn.rollback(); raise
        finally: conn.close()
        return self._generation(request.generation_id)
    def _generation(self,generation_id):
        conn=self.connect()
        try:
            row=conn.execute("SELECT checksum,analyzer_version,revision_set_json,representation_versions_json,capabilities_json,quarantined_count,doc_count,created_at FROM lexical_generations WHERE generation_id=?",(generation_id,)).fetchone()
            if row is None:return None
            docs=conn.execute("SELECT passage_uid,revision_uid,locator_json,original_text FROM lexical_fts WHERE generation_id=? ORDER BY passage_uid",(generation_id,)).fetchall()
            visible=conn.execute("SELECT COUNT(*) FROM lexical_fts WHERE generation_id=?",(generation_id,)).fetchone()[0]==row[6]
            payloads=tuple(ProjectionPayload(p,r,l,sha256_hex(t.encode("utf-8")),t) for p,r,l,t in docs)
            revisions=tuple(json.loads(row[2]))
            referential=all(r in set(revisions) for _,r,_,_ in docs)
            return ProjectionGeneration(generation_id,"lexical",revisions,tuple(json.loads(row[3])),row[0],True,visible,referential,int(row[5]),tuple(json.loads(row[4])),_dt(row[7]),payloads)
        finally:conn.close()
    def validate(self,generation):
        current=self._generation(generation.generation_id)
        return bool(current and current.checksum==generation.checksum and current.ready and current.visible and current.referential_integrity)
    def cleanup(self,generation_id):
        conn=self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE"); conn.execute("DELETE FROM lexical_fts WHERE generation_id=?",(generation_id,)); conn.execute("DELETE FROM lexical_generations WHERE generation_id=?",(generation_id,)); conn.commit()
        except Exception: conn.rollback(); raise
        finally:conn.close()
    async def search(self,request):
        if request.snapshot is None:return ChannelResult(ChannelStatus.REJECTED,reason="lexical backend requires pinned snapshot")
        generation_id=self.catalog.generation_for_manifest(request.snapshot.manifest_id,"lexical")
        if generation_id is None:return ChannelResult(ChannelStatus.REJECTED,reason="snapshot has no lexical generation")
        expression=_safe_match(request.query)
        if expression is None:return ChannelResult(ChannelStatus.EMPTY,reason="query has no lexical tokens")
        clauses=["lexical_fts MATCH ?","generation_id=?"]; params=[expression,generation_id]
        tenants=tuple(dict.fromkeys((request.scope.tenant_id,"public"))); clauses.append("tenant_id IN ("+",".join("?" for _ in tenants)+")"); params.extend(tenants)
        domains=tuple(request.scope.domains); clauses.append("domain IN ("+",".join("?" for _ in domains)+")"); params.extend(domains)
        labels=tuple(v.value for v in request.scope.access_labels); clauses.append("access_label IN ("+",".join("?" for _ in labels)+")"); params.extend(labels)
        if request.scope.source_ids:
            clauses.append("source_id IN ("+",".join("?" for _ in request.scope.source_ids)+")"); params.extend(request.scope.source_ids)
        if request.temporal.mode==TemporalMode.HISTORICAL_PUBLIC:
            if not request.temporal.cutoff_iso:return ChannelResult(ChannelStatus.REJECTED,reason="historical public search requires cutoff")
            cutoff=_iso(datetime.fromisoformat(request.temporal.cutoff_iso.replace("Z","+00:00")))
            clauses.append("available_at IS NOT NULL AND available_at<=?"); params.append(cutoff)
        elif request.temporal.mode==TemporalMode.CURRENT:
            clauses.append("(available_at IS NULL OR available_at<=?)"); params.append(_iso(datetime.now(timezone.utc)))
        revoked=tuple(self.catalog.revoked_uids())
        if revoked:
            marks=",".join("?" for _ in revoked)
            clauses.extend((f"revision_uid NOT IN ({marks})",f"passage_uid NOT IN ({marks})",f"object_uid NOT IN ({marks})"))
            params.extend(revoked); params.extend(revoked); params.extend(revoked)
        limit=min(request.budget.total,request.budget.lexical or request.budget.total)
        sql="""SELECT passage_uid,revision_uid,locator_json,original_text,bm25(lexical_fts) AS score
               FROM lexical_fts WHERE """+" AND ".join(clauses)+" ORDER BY score ASC, passage_uid ASC LIMIT ?"
        params.append(limit)
        conn=self.connect()
        try: rows=conn.execute(sql,tuple(params)).fetchall()
        except sqlite3.OperationalError as exc:return ChannelResult(ChannelStatus.REJECTED,reason=f"invalid lexical query: {exc}")
        finally:conn.close()
        if not rows:return ChannelResult(ChannelStatus.EMPTY,reason="no authorized lexical matches")
        hits=[]
        for rank,(passage_uid,revision_uid,locator_json,text,score) in enumerate(rows,1):
            locator=locator_from_dict(json.loads(locator_json))
            hit_id=namespaced_uid("hit","lexical.search",{"manifest":request.snapshot.manifest_id,"passage_uid":passage_uid,"query":request.query})
            hits.append(PassageHit(hit_id,passage_uid,revision_uid,ProvenanceRef(revision_uid,locator),text,(ScoreMetadata("lexical",float(score),ScoreDirection.LOWER_IS_BETTER,rank,"sqlite-fts5"),)))
        return ChannelResult(ChannelStatus.OK,tuple(hits))
