"""Fail-closed tuning selection with one-shot holdout evaluation."""
from __future__ import annotations
from .models import CandidateDecision,MeasurementKind,OptimizationDecision

def _eligible(plan,baseline,row):
    reasons=[]
    if not row.hard_gate_pass:reasons.append("hard_gate")
    if not row.exact_structured_pass:reasons.append("exact_structured")
    if not row.critical_slice_noninferior:reasons.append("critical_slice")
    if row.ndcg_at_10<baseline.ndcg_at_10-plan.ndcg_noninferiority_margin:reasons.append("ndcg_noninferiority")
    if row.recall_at_50<baseline.recall_at_50-plan.recall50_noninferiority_margin:reasons.append("recall50_noninferiority")
    if row.p95_latency_ms>plan.max_p95_latency_ms:reasons.append("p95_latency_budget")
    if plan.max_ram_mb is not None and row.ram_peak_mb>plan.max_ram_mb:reasons.append("ram_budget")
    return not reasons,tuple(reasons)

def select_optimization(plan,configs,observations):
    configs={c.config_id:c for c in configs};observations=tuple(observations)
    if plan.baseline_config_id not in configs:raise ValueError("baseline configuration is missing")
    tuning=[o for o in observations if o.split=="tuning"];holdout=[o for o in observations if o.split=="holdout"]
    baseline_rows=[o for o in tuning if o.config_id==plan.baseline_config_id]
    if len(baseline_rows)!=1:raise ValueError("exactly one tuning baseline observation is required")
    baseline=baseline_rows[0];decisions=[];eligible=[]
    seen=set()
    for row in tuning:
        if row.config_id in seen:raise ValueError("duplicate tuning observation")
        seen.add(row.config_id)
        if row.config_id not in configs:raise ValueError("observation references unknown config")
        ok,reasons=_eligible(plan,baseline,row)
        decisions.append(CandidateDecision(row.config_id,ok,reasons,row.p95_latency_ms-baseline.p95_latency_ms,row.backend_read_ops-baseline.backend_read_ops))
        if ok:eligible.append(row)
    if not eligible:choice=plan.baseline_config_id
    else:choice=min(eligible,key=lambda r:(r.p95_latency_ms,r.backend_read_ops,r.ram_peak_mb,r.config_id)).config_id
    allowed_holdout={plan.baseline_config_id,choice}
    if any(o.config_id not in allowed_holdout for o in holdout):raise ValueError("holdout contains configurations not selected by tuning")
    choice_rows=[o for o in holdout if o.config_id==choice]
    baseline_holdout=[o for o in holdout if o.config_id==plan.baseline_config_id]
    holdout_evaluated=bool(choice_rows) if choice!=plan.baseline_config_id else bool(baseline_holdout)
    production=plan.baseline_config_id;status="blocked";reason="selected candidate lacks required real-runtime holdout evidence"
    if choice==plan.baseline_config_id:
        production=plan.baseline_config_id;status="passed";reason="tuning retained the baseline"
    elif len(choice_rows)==1 and len(baseline_holdout)==1:
        chosen=choice_rows[0];base=baseline_holdout[0];ok,reasons=_eligible(plan,base,chosen)
        if not ok:
            status="failed";reason="selected tuning candidate failed one-shot holdout: "+",".join(reasons)
        elif plan.require_real_runtime_for_promotion and (chosen.measurement_kind!=MeasurementKind.REAL_RUNTIME or base.measurement_kind!=MeasurementKind.REAL_RUNTIME):
            status="blocked";reason="fixture holdout passed mechanics but real-runtime latency/resource evidence is required"
        else:
            production=choice;status="passed";reason="candidate passed one-shot holdout and promotion requirements"
    elif choice!=plan.baseline_config_id:
        status="not_run";reason="selected tuning candidate has not been evaluated on holdout"
    return OptimizationDecision(plan.plan_id,choice,production,status,reason,tuple(sorted(decisions,key=lambda d:d.config_id)),holdout_evaluated)
