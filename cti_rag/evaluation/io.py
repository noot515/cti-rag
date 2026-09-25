"""Strict JSONL loaders for frozen evaluation data and run outputs."""
from __future__ import annotations
import json
from pathlib import Path
from .models import *

def _lines(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():yield json.loads(line)

def load_queries(path):
    return tuple(EvaluationQuery(
        row["query_id"],row["domain"],row["text"],row["task_type"],row["source_family"],row["duplicate_group"],row["split"],row["temporal_bucket"],bool(row["answerable"]),
        tuple(row.get("required_routes",())),tuple(row.get("required_subquestions",())),tuple(row.get("adversarial_tags",())),row.get("locale","en-US")
    ) for row in _lines(path))

def load_judgments(path):
    return tuple(RelevanceJudgment(
        row["query_id"],JudgmentStatus(row["status"]),tuple((str(uid),int(grade)) for uid,grade in row.get("relevance",())),
        tuple(tuple(map(str,v)) for v in row.get("expected_structured",())),tuple(row.get("expected_citations",())),tuple(row.get("required_graph_edges",())),
        tuple(row.get("reviewer_ids",())),row.get("notes")
    ) for row in _lines(path))

def load_runs(path):
    data=json.loads(Path(path).read_text(encoding="utf-8"));out=[]
    for row in data["runs"]:
        m=row["metadata"];metadata=RunMetadata(m["baseline"],m["scope_hash"],m["snapshot_id"],int(m["candidate_budget"]),m["resource_condition"],ModelExecutionKind(m.get("model_execution","none")),tuple(m.get("model_fingerprints",())),tuple(m.get("provider_fingerprints",())),m.get("config_fingerprint","evaluation/default"))
        outcomes=tuple(QueryOutcome(
            x["query_id"],tuple(x.get("returned_uids",())),tuple(x.get("returned_origin_groups",())),tuple(x.get("router_routes",())),tuple(x.get("ann_ids",())),tuple(x.get("exhaustive_ann_ids",())),tuple(x.get("covered_subquestions",())),tuple(x.get("covered_graph_edges",())),tuple(tuple(map(str,v)) for v in x.get("structured_values",())),tuple(x.get("packed_uids",())),tuple((str(v[0]),bool(v[1])) for v in x.get("citations",())),bool(x.get("answered",False)),bool(x.get("abstained",False)),bool(x.get("answer_error",False)),float(x.get("latency_ms",0)),tuple((str(k),float(v)) for k,v in x.get("stage_latency_ms",())),x.get("ram_peak_mb"),x.get("vram_peak_mb"),bool(x.get("backend_failure",False)),bool(x.get("policy_failure",False)),bool(x.get("temporal_failure",False)),tuple(x.get("returned_source_families",()))
        ) for x in row["outcomes"])
        out.append(EvaluationRun(metadata,outcomes))
    return tuple(out)
