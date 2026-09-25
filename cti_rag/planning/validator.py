"""Static plan validation: authorization subset, cycles, and server budgets."""
from __future__ import annotations
from .models import PlanValidationError

def validate_plan(plan):
    nodes={n.node_id:n for n in plan.nodes}
    if len(nodes)!=len(plan.nodes): raise PlanValidationError("duplicate plan node id")
    if len(nodes)>plan.budget.max_backend_calls: raise PlanValidationError("plan exceeds backend-call budget")
    if sum(n.candidate_limit for n in plan.nodes)>plan.budget.max_total_candidates: raise PlanValidationError("plan exceeds candidate budget")
    allowed_domains=set(plan.scope.domains)
    for node in plan.nodes:
        if not set(node.domains).issubset(allowed_domains): raise PlanValidationError("plan node domain exceeds authorized scope")
        for dep in node.dependencies:
            if dep not in nodes: raise PlanValidationError(f"unknown dependency: {dep}")
    state={}
    def visit(node_id):
        mark=state.get(node_id,0)
        if mark==1: raise PlanValidationError("cyclic query plan")
        if mark==2:return
        state[node_id]=1
        for dep in nodes[node_id].dependencies: visit(dep)
        state[node_id]=2
    for node_id in nodes: visit(node_id)
    return plan
