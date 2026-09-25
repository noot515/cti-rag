"""Reproducible B0-B8 evaluation harness over frozen query/judgment sets."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import asdict
import hashlib,json
from .bootstrap import paired_bootstrap
from .metrics import aggregate,hard_failure_counts,query_metrics
from .models import EvaluationRun,ExperimentConfig,JudgmentStatus,ModelExecutionKind

PAIRWISE_ABLATIONS=(("B1","B3"),("B2","B3"),("B3","B4"),("B4","B5"),("B4","B6"),("B4","B7"),("B7","B8"))
BASELINE_DEFINITIONS={
    "B0":"captured_legacy_public_fixture",
    "B1":"independent_lexical",
    "B2":"dense",
    "B3":"lexical_dense_equal_rrf",
    "B4":"b3_plus_optional_text_reranker",
    "B5":"b4_plus_structure_prefix_parent_expansion",
    "B6":"b4_plus_bounded_graph_expansion",
    "B7":"b4_plus_task_routing_structured_execution",
    "B8":"best_validated_plus_bounded_contradiction_search",
}

def _canonical(value):return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def fingerprint(value):return hashlib.sha256(_canonical(value).encode()).hexdigest()
def _validate_conditions(config,run):
    m=run.metadata
    if m.baseline not in BASELINE_DEFINITIONS:raise ValueError("unsupported B0-B8 baseline")
    if m.baseline not in config.baselines:raise ValueError("run baseline not predeclared")
    if m.scope_hash!=config.scope_hash or m.snapshot_id!=config.snapshot_id or m.candidate_budget!=config.candidate_budget or m.resource_condition!=config.resource_condition:
        raise ValueError("baseline comparison conditions differ from experiment config")
def _rows(queries,judgments,run):
    qmap={q.query_id:q for q in queries};jmap={j.query_id:j for j in judgments};omap={o.query_id:o for o in run.outcomes}
    missing=set(qmap)-set(omap)
    if missing:raise ValueError("run is missing frozen query outcomes: "+",".join(sorted(missing)[:5]))
    return {qid:query_metrics(qmap[qid],jmap[qid],omap[qid]) for qid in sorted(qmap)}
def _slices(queries,rows):
    groups=defaultdict(list);qmap={q.query_id:q for q in queries}
    for qid,row in rows.items():
        q=qmap[qid];groups[f"domain:{q.domain}"].append(row);groups[f"task:{q.task_type}"].append(row)
        for tag in q.adversarial_tags:groups[f"adversarial:{tag}"].append(row)
    return {name:{"n":len(values),"metrics":aggregate(values)} for name,values in sorted(groups.items())}
def _run_report(config,queries,judgments,run):
    _validate_conditions(config,run);rows=_rows(queries,judgments,run)
    hard=hard_failure_counts(queries,judgments,run.outcomes)
    quality_status="eligible" if run.metadata.model_execution==ModelExecutionKind.REAL_MODEL else "not_run_fake_or_no_model"
    metadata=asdict(run.metadata);metadata["model_execution"]=run.metadata.model_execution.value
    result={
        "baseline":run.metadata.baseline,"definition":BASELINE_DEFINITIONS[run.metadata.baseline],
        "metadata":metadata,"n":len(rows),"metrics":aggregate(list(rows.values())),
        "slices":_slices(queries,rows),"hard_failures":hard,"hard_gate_pass":all(v==0 for v in hard.values()),
        "semantic_model_metrics_status":quality_status,
        "query_metrics":rows,
    }
    if run.metadata.model_execution!=ModelExecutionKind.REAL_MODEL:
        result["semantic_model_metrics"]={}
    return result
def _paired(config,base,candidate,queries):
    common=sorted(set(base["query_metrics"])&set(candidate["query_metrics"]));qmap={q.query_id:q for q in queries}
    comparisons={}
    for metric,margin in (("ndcg@10",config.ndcg_noninferiority_margin),("recall@50",config.recall50_noninferiority_margin)):
        b=[base["query_metrics"][q][metric] for q in common];c=[candidate["query_metrics"][q][metric] for q in common]
        comparisons[metric]=paired_bootstrap(c,b,replicates=config.bootstrap_replicates,confidence=config.confidence,seed=config.seed,min_pairs=config.min_conclusive_pairs,noninferiority_margin=margin)
        slices={}
        for key in sorted({f"domain:{qmap[q].domain}" for q in common}|{f"task:{qmap[q].task_type}" for q in common}):
            kind,value=key.split(":",1);ids=[q for q in common if getattr(qmap[q],"task_type" if kind=="task" else kind)==value]
            slices[key]=paired_bootstrap([candidate["query_metrics"][q][metric] for q in ids],[base["query_metrics"][q][metric] for q in ids],replicates=config.bootstrap_replicates,confidence=config.confidence,seed=config.seed,min_pairs=config.min_conclusive_pairs,noninferiority_margin=margin)
        comparisons[metric]["slices"]=slices
    return comparisons

def run_experiment(config:ExperimentConfig,queries,judgments,runs):
    queries=tuple(queries);judgments=tuple(judgments);runs=tuple(runs)
    qids=[q.query_id for q in queries];jids=[j.query_id for j in judgments]
    if len(qids)!=len(set(qids)) or len(jids)!=len(set(jids)) or set(qids)!=set(jids):raise ValueError("query/judgment identities must be unique and complete")
    run_reports={run.metadata.baseline:_run_report(config,queries,judgments,run) for run in runs}
    comparisons={}
    if "B0" in run_reports:
        for name in sorted(run_reports):
            if name!="B0":comparisons[f"B0->{name}"]=_paired(config,run_reports["B0"],run_reports[name],queries)
    for base,candidate in PAIRWISE_ABLATIONS:
        if base in run_reports and candidate in run_reports:
            comparisons[f"{base}->{candidate}"]=_paired(config,run_reports[base],run_reports[candidate],queries)
    report={
        "schema_version":"multidomain-evaluation-report/1","experiment":asdict(config),
        "dataset":{"query_count":len(queries),"judgment_count":len(judgments),"human_reviewed":sum(j.status==JudgmentStatus.HUMAN_REVIEWED for j in judgments),"machine_generated_unreviewed":sum(j.status==JudgmentStatus.MACHINE_GENERATED_UNREVIEWED for j in judgments),"synthetic_contract":sum(j.status==JudgmentStatus.SYNTHETIC_CONTRACT for j in judgments)},
        "runs":run_reports,"paired_comparisons":comparisons,
    }
    report["report_digest"]=fingerprint(report)
    return report
