"""Deterministic retrieval, grounding, abstention, policy, and resource metrics."""
from __future__ import annotations
import math
from collections import Counter
from statistics import median

def _relevance_map(judgment):return {uid:int(grade) for uid,grade in judgment.relevance}
def _relevant(judgment):return {uid for uid,grade in judgment.relevance if int(grade)>0}
def recall_at(ranking,relevant,k):
    relevant=set(relevant)
    if not relevant:return 1.0
    return len(set(tuple(ranking)[:k])&relevant)/len(relevant)
def reciprocal_rank(ranking,relevant):
    relevant=set(relevant)
    for idx,uid in enumerate(tuple(ranking),1):
        if uid in relevant:return 1.0/idx
    return 0.0
def ndcg_at(ranking,grades,k):
    grades=dict(grades)
    gains=[grades.get(uid,0) for uid in tuple(ranking)[:k]]
    def dcg(values):return sum((2**grade-1)/math.log2(i+2) for i,grade in enumerate(values))
    ideal=sorted((int(v) for v in grades.values()),reverse=True)[:k]
    denom=dcg(ideal)
    return 1.0 if denom==0 else dcg(gains)/denom
def coverage(actual,required):
    required=set(required)
    if not required:return 1.0
    return len(set(actual)&required)/len(required)
def percentile(values,p):
    values=sorted(float(v) for v in values)
    if not values:return None
    if len(values)==1:return values[0]
    pos=(len(values)-1)*p;lo=int(math.floor(pos));hi=int(math.ceil(pos))
    if lo==hi:return values[lo]
    return values[lo]+(values[hi]-values[lo])*(pos-lo)
def duplicate_origin_excess(outcome,k=10):
    groups=tuple(outcome.returned_origin_groups)[:k]
    if not groups:return 0
    counts=Counter(groups)
    return sum(max(0,n-1) for n in counts.values())

def query_metrics(query,judgment,outcome):
    rel=_relevant(judgment);grades=_relevance_map(judgment)
    metrics={
        "recall@20":recall_at(outcome.returned_uids,rel,20),
        "recall@50":recall_at(outcome.returned_uids,rel,50),
        "recall@100":recall_at(outcome.returned_uids,rel,100),
        "mrr":reciprocal_rank(outcome.returned_uids,rel),
        "ndcg@10":ndcg_at(outcome.returned_uids,grades,10),
        "router_recall":coverage(outcome.router_routes,query.required_routes),
        "ann_recall":recall_at(outcome.ann_ids,set(outcome.exhaustive_ann_ids),len(outcome.exhaustive_ann_ids) or 1),
        "subquestion_coverage":coverage(outcome.covered_subquestions,query.required_subquestions),
        "graph_coverage":coverage(outcome.covered_graph_edges,judgment.required_graph_edges),
        "structured_correctness":1.0 if tuple(sorted(outcome.structured_values))==tuple(sorted(judgment.expected_structured)) else 0.0,
        "packing_survival":coverage(outcome.packed_uids,set(outcome.returned_uids)&rel),
        "citation_support":1.0 if not outcome.citations else sum(1 for _uid,supported in outcome.citations if supported)/len(outcome.citations),
        "answerable_coverage":1.0 if (not query.answerable or outcome.answered) else 0.0,
        "false_abstention":1.0 if query.answerable and outcome.abstained else 0.0,
        "error_among_answered":1.0 if outcome.answered and outcome.answer_error else 0.0,
        "latency_ms":float(outcome.latency_ms),
        "duplicate_origin_excess":float(duplicate_origin_excess(outcome)),
        "backend_failure":1.0 if outcome.backend_failure else 0.0,
        "policy_failure":1.0 if outcome.policy_failure else 0.0,
        "temporal_failure":1.0 if outcome.temporal_failure else 0.0,
    }
    for name,value in outcome.stage_latency_ms:metrics[f"stage_latency_ms:{name}"]=float(value)
    if outcome.ram_peak_mb is not None:metrics["ram_peak_mb"]=float(outcome.ram_peak_mb)
    if outcome.vram_peak_mb is not None:metrics["vram_peak_mb"]=float(outcome.vram_peak_mb)
    return metrics

def hard_failure_counts(queries,judgments,outcomes):
    jmap={j.query_id:j for j in judgments};omap={o.query_id:o for o in outcomes}
    counts={"router_miss":0,"future_revision_leak":0,"duplicate_source_boost":0,"wrong_structured_result":0,"unsupported_citation":0,"policy_exposure":0}
    for q in queries:
        j=jmap[q.query_id];o=omap[q.query_id];m=query_metrics(q,j,o)
        if q.required_routes and m["router_recall"]<1:counts["router_miss"]+=1
        if o.temporal_failure:counts["future_revision_leak"]+=1
        if "duplicate_source_boost" in q.adversarial_tags and m["duplicate_origin_excess"]>0:counts["duplicate_source_boost"]+=1
        if j.expected_structured and m["structured_correctness"]<1:counts["wrong_structured_result"]+=1
        counts["unsupported_citation"]+=sum(1 for _uid,supported in o.citations if not supported)
        if o.policy_failure:counts["policy_exposure"]+=1
    return counts

def aggregate(query_metric_rows):
    if not query_metric_rows:return {}
    keys=sorted({k for row in query_metric_rows for k in row})
    out={}
    for key in keys:
        values=[float(row[key]) for row in query_metric_rows if key in row]
        if not values:continue
        if key=="latency_ms" or key.startswith("stage_latency_ms:"):
            out[key]={"p50":median(values),"p95":percentile(values,.95),"mean":sum(values)/len(values),"n":len(values)}
        elif key in ("ram_peak_mb","vram_peak_mb"):
            out[key]={"max":max(values),"p95":percentile(values,.95),"n":len(values)}
        else:out[key]=sum(values)/len(values)
    return out
