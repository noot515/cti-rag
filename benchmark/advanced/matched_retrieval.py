"""Deterministic matched-corpus exact/BM25 parity and latency measurement."""
from __future__ import annotations
from collections import Counter
import math
from pathlib import Path
from typing import Any, Mapping, Sequence
from benchmark.advanced.matched_config import MatchedConfig, QuerySpec
from packages.evidence.ids import canonical_hash
from packages.evidence.policy import ResolvedScope
from packages.evidence.schema import ExternalIdentifier, SnapshotRef
from packages.evidence.store import EvidenceStore
from packages.indexing.chunker import DeterministicTokenizer
from packages.retrieval.exact import ExactIndex
from packages.retrieval.lexical import LexicalIndex

def _direct_bm25(batch, tokenizer, query, k1, b):
    docs, df, total = [], Counter(), 0
    for chunk in batch.chunks:
        tokens = tokenizer.tokens(chunk.text); docs.append((chunk.object_uid, tokens)); total += len(tokens)
        for term in set(tokens): df[term] += 1
    avg = total / len(docs) if docs else 0.; terms = tuple(dict.fromkeys(tokenizer.tokens(query))); scores = []
    for uid, tokens in docs:
        tf, score = Counter(tokens), 0.
        for term in terms:
            freq, dfi = tf.get(term, 0), df.get(term, 0)
            if not freq or not dfi: continue
            idf = math.log((len(docs)-dfi+.5)/(dfi+.5)+1); denom = freq+k1*(1-b+(b*len(tokens)/avg if avg else 0)); score += idf*(freq*(k1+1)/denom)
        if score > 0: scores.append((uid, score))
    return scores

def _rank(pairs, uid_map, top_k):
    best = {}
    for uid, score in pairs:
        source = uid_map.get(uid)
        if source is not None: best[source] = max(best.get(source, float("-inf")), float(score))
    return [{"source_object_id": source, "score": score} for source, score in sorted(best.items(), key=lambda x:(-x[1],x[0]))[:top_k]]

def _imap(store, manifest):
    rows = store.connection.execute("SELECT DISTINCT r.object_uid,s.source_object_id,s.source_instance FROM snapshot_membership sm JOIN object_revisions r ON r.domain=sm.domain AND r.scope_id=sm.scope_id AND r.object_uid=sm.evidence_uid AND r.revision_uid=sm.revision_uid JOIN object_revision_sources s ON s.domain=r.domain AND s.scope_id=r.scope_id AND s.revision_uid=r.revision_uid WHERE sm.domain=? AND sm.scope_id=? AND sm.snapshot_id=? AND sm.evidence_kind='object'", (manifest.domain, manifest.scope_id, manifest.generation_id)).fetchall()
    return {str(r["object_uid"]): str(r["source_object_id"]) for r in rows}, tuple(sorted({str(r["source_instance"]) for r in rows}))

def _scope(manifest, sources):
    scope = ResolvedScope(principal_id="matched-eval", principal_namespace="trusted-eval", corpus_id=manifest.corpus_id, domain=manifest.domain, scope_id=manifest.scope_id, active_catalog_id=manifest.generation_id, policy_version="matched-eval-v1", source_allowlist=frozenset(sources), allowed_destinations=frozenset({"caller"}))
    return scope, SnapshotRef(domain=manifest.domain, scope_id=manifest.scope_id, snapshot_id=manifest.generation_id, manifest_sha256=manifest.manifest_sha256)

def compare_retrieval(batch, tokenizer, store: EvidenceStore, state: Path, manifest, config: MatchedConfig) -> dict[str, Any]:
    direct_uid = {o.uid:o.source_refs[0].source_object_id for o in batch.objects}; ingested_uid, sources = _imap(store,manifest); scope,snap = _scope(manifest,sources)
    lexical = LexicalIndex.open(store,path=LexicalIndex.path_for(state/"indexes",domain=manifest.domain,scope_id=manifest.scope_id,generation_id=manifest.generation_id),tokenizer=tokenizer); exact=ExactIndex.open(store,path=ExactIndex.path_for(state/"indexes",domain=manifest.domain,scope_id=manifest.scope_id,generation_id=manifest.generation_id))
    direct_exact = {}
    for obj in batch.objects:
        for ident in obj.external_ids: direct_exact.setdefault((ident.namespace,ident.value),[]).append(obj.uid)
    reports=[]; rank_bad=exact_bad=0; max_delta=0.
    for q in config.queries:
        direct = _rank(_direct_bm25(batch,tokenizer,q.text,config.lexical_k1,config.lexical_b),direct_uid,config.top_k); hits=lexical.search(q.text,scope=scope,snapshot=snap,top_k=max(config.top_k*4,config.top_k)); ingested=_rank([(str(h.metadata["object_uid"]),float(h.raw_score or 0.)) for h in hits],ingested_uid,config.top_k)
        did,iid=[x["source_object_id"] for x in direct],[x["source_object_id"] for x in ingested]; bad=sum(a!=b for a,b in zip(did,iid))+abs(len(did)-len(iid)); rank_bad+=bad
        ds,ins={x["source_object_id"]:x["score"] for x in direct},{x["source_object_id"]:x["score"] for x in ingested}; delta=max((abs(ds[k]-ins[k]) for k in set(ds)&set(ins)),default=0.); max_delta=max(max_delta,delta); de=ie=None
        if q.namespace:
            de=[direct_uid[u] for u in direct_exact.get((str(q.namespace),str(q.value)),()) if u in direct_uid]; ih=exact.lookup(ExternalIdentifier(namespace=str(q.namespace),value=str(q.value),domain="cti"),scope=scope,snapshot=snap,top_k=config.top_k); ie=[ingested_uid[str(h.metadata["object_uid"])] for h in ih if str(h.metadata["object_uid"]) in ingested_uid]
            if de!=ie: exact_bad+=1
        reports.append({"query_id":q.query_id,"lexical_direct":direct,"lexical_ingested":ingested,"rank_mismatches":bad,"max_score_delta":delta,"exact_direct":de,"exact_ingested":ie})
    ok=rank_bad<=config.rank_mismatch_tolerance and max_delta<=config.score_abs_tolerance and exact_bad==0
    ann=dict(config.ann_settings)
    ann["status"]="not_run"
    if ann.get("enabled"):
        ann["reason"]="ANN execution is a separate real-service gate and is not exercised by the deterministic matched-corpus comparator"
    return {"status":"pass" if ok else "fail","top_k":config.top_k,"pre_rerank_limit":config.pre_rerank_limit,"context_budget":config.context_budget,"query_split_sha256":canonical_hash(["matched-query-split-v1",[q.query_id for q in config.queries]]),"lexical":{"k1":config.lexical_k1,"b":config.lexical_b},"ann":ann,"models":config.models,"observed_rank_mismatches":rank_bad,"observed_max_abs_score_delta":max_delta,"exact_query_mismatches":exact_bad,"queries":reports}

def _percentile(values, fraction):
    if not values:return None
    xs=sorted(values); pos=fraction*(len(xs)-1); lo,hi=math.floor(pos),math.ceil(pos); return xs[lo] if lo==hi else xs[lo]*(hi-pos)+xs[hi]*(pos-lo)

def measure_latency(store: EvidenceStore,state:Path,manifest,queries:Sequence[QuerySpec],config:MatchedConfig)->dict[str,Any]:
    import time
    _,sources=_imap(store,manifest); scope,snap=_scope(manifest,sources); path=LexicalIndex.path_for(state/"indexes",domain=manifest.domain,scope_id=manifest.scope_id,generation_id=manifest.generation_id); cold=[];warm=[];errors=0
    for _ in range(config.cold_repeats):
        for q in queries:
            started=time.perf_counter()
            try:LexicalIndex.open(store,path=path,tokenizer=DeterministicTokenizer()).search(q.text,scope=scope,snapshot=snap,top_k=config.top_k)
            except Exception:errors+=1
            else:cold.append((time.perf_counter()-started)*1000)
    index=LexicalIndex.open(store,path=path,tokenizer=DeterministicTokenizer())
    for _ in range(config.warm_repeats):
        for q in queries:
            started=time.perf_counter()
            try:index.search(q.text,scope=scope,snapshot=snap,top_k=config.top_k)
            except Exception:errors+=1
            else:warm.append((time.perf_counter()-started)*1000)
    summarize=lambda xs,n:{"repeat_count":n,"concurrency":1,"sample_count":len(xs),"p50_ms":_percentile(xs,.5),"p95_ms":_percentile(xs,.95)}
    return {"cold":summarize(cold,config.cold_repeats),"warm":summarize(warm,config.warm_repeats),"errors":errors}

__all__=["compare_retrieval","measure_latency"]
