"""Deterministic query feature extraction and task-template planner before optional semantic planning."""
from __future__ import annotations
import re
from dataclasses import replace
from cti_rag.identifiers import default_identifier_registry
from .models import EvidenceObligation,PlanBudget,PlanGap,PlanNode,PlanOperation,QueryFeatures,QueryIntent,QueryPlan,Subquestion
from .validator import validate_plan

_IDENTIFIER_PATTERNS=(
    re.compile(r"CVE-[0-9]{4}-[0-9]{4,}",re.I),re.compile(r"CWE-[0-9]+",re.I),re.compile(r"T[0-9]{4}(?:\.[0-9]{3})?",re.I),
    re.compile(r"AS[0-9]+",re.I),re.compile(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}"),re.compile(r"RFC[ -]?[0-9]+",re.I),
    re.compile(r"10\.[0-9]{4,9}/[^\s,;]+",re.I),re.compile(r"(?:97[89])?[0-9]{9}[0-9X]",re.I),
)
_DATE=re.compile(r"\b(?:19|20)[0-9]{2}(?:-[01][0-9](?:-[0-3][0-9])?)?\b")
_UNIT=re.compile(r"(?<!\w)(?:USD|EUR|JPY|GBP|%|ms|s|GB|GiB|MB|bps|kbps|Mbps|Gbps)(?!\w)",re.I)

class DeterministicQueryPlanner:
    def __init__(self,identifier_registry=None,semantic_planner=None,server_budget=PlanBudget()):
        self.identifiers=identifier_registry or default_identifier_registry(); self.semantic_planner=semantic_planner; self.server_budget=server_budget; self.semantic_calls=0
    def extract_features(self,query):
        found=[]; seen=set()
        for pattern in _IDENTIFIER_PATTERNS:
            for m in pattern.finditer(query):
                parsed=self.identifiers.parse_one(m.group(0))
                if parsed:
                    key=(parsed.namespace,parsed.object_type,parsed.canonical)
                    if key not in seen:seen.add(key);found.append(key)
        return QueryFeatures(tuple(found),tuple(dict.fromkeys(_DATE.findall(query))),tuple(dict.fromkeys(m.group(0) for m in _UNIT.finditer(query))))
    def _budget(self,requested):
        if requested is None:return self.server_budget
        return PlanBudget(
            deadline_ms=min(requested.deadline_ms,self.server_budget.deadline_ms),max_backend_calls=min(requested.max_backend_calls,self.server_budget.max_backend_calls),
            max_expansion_rounds=min(requested.max_expansion_rounds,self.server_budget.max_expansion_rounds),max_total_candidates=min(requested.max_total_candidates,self.server_budget.max_total_candidates),
            max_rerank_candidates=min(requested.max_rerank_candidates,self.server_budget.max_rerank_candidates),max_context_tokens=min(requested.max_context_tokens,self.server_budget.max_context_tokens),
        )
    def _domains(self,query,scope):
        q=query.lower(); scores={d:0 for d in scope.domains}
        hints={"cybersecurity":("cve","cwe","vulnerability","attack","malware","exploit"),"networking":("rfc","bgp","route","asn","cidr","dns","network"),"quant":("return","price","stock","filing","fred","sec","yield"),"privacy":("privacy","tracker","broker","osint","exposure"),"humanities":("edition","translation","archive","tei","novel","poem","historical")}
        for domain,words in hints.items():
            if domain in scores:scores[domain]=sum(1 for w in words if w in q)
        best=max(scores.values()) if scores else 0
        if best==0:return tuple(sorted(scope.domains)[:min(2,len(scope.domains))]),True
        return tuple(sorted(d for d,v in scores.items() if v==best and v>0)),False
    def compile(self,query,scope,snapshot,temporal,available_operations,requested_budget=None):
        normalized=" ".join(query.split()); features=self.extract_features(query); budget=self._budget(requested_budget); domains,fallback=self._domains(query,scope); ops=set(available_operations)
        qlow=normalized.lower(); nodes=[]; obligations=[]; gaps=[]; subquestions=(Subquestion("q0",normalized),)
        exact_only=False
        if len(features.identifiers)==1:
            canonical=features.identifiers[0][2]
            compact=re.sub(r"[^A-Za-z0-9./:-]","",normalized).upper()
            exact_only=compact==re.sub(r"[^A-Za-z0-9./:-]","",canonical).upper()
        numerical=bool(re.search(r"\b(count|average|mean|sum|return|price|ratio|percent|percentage|how many)\b",qlow)) or bool(features.units)
        relation=bool(re.search(r"\b(related|relationship|connected|maps? to|depends on|owns?|announces?|updates?)\b",qlow))
        if exact_only:intent=QueryIntent.EXACT
        elif numerical:intent=QueryIntent.NUMERICAL
        elif relation:intent=QueryIntent.RELATION
        elif len(domains)>1:intent=QueryIntent.CROSS_DOMAIN
        else:intent=QueryIntent.EXPLANATION
        if features.identifiers:
            for i,(_namespace,_obj_type,canonical) in enumerate(features.identifiers):
                obligations.append(EvidenceObligation(f"exact-{i}","exact",canonical,True,"q0"))
                if PlanOperation.EXACT in ops:nodes.append(PlanNode(f"exact-{i}",PlanOperation.EXACT,canonical,"q0",1,domains,required=True))
                else:gaps.append(PlanGap("exact",f"exact capability unavailable for {canonical}"))
        if exact_only:
            return validate_plan(QueryPlan(query,normalized,intent,scope,snapshot,temporal,budget,features,tuple(nodes),tuple(obligations),tuple(gaps),domains if fallback else (),subquestions))
        if numerical:
            obligations.append(EvidenceObligation("structured-0","structured",normalized,True,"q0"))
            if PlanOperation.STRUCTURED in ops:nodes.append(PlanNode("structured-0",PlanOperation.STRUCTURED,normalized,"q0",1,domains,required=True))
            else:gaps.append(PlanGap("structured","structured capability unavailable"))
        if relation:
            if PlanOperation.GRAPH in ops:nodes.append(PlanNode("graph-0",PlanOperation.GRAPH,normalized,"q0",20,domains))
            else:gaps.append(PlanGap("graph","graph capability unavailable"))
        if PlanOperation.LEXICAL in ops:nodes.append(PlanNode("lexical-0",PlanOperation.LEXICAL,normalized,"q0",50,domains,variant_key="base"))
        else:gaps.append(PlanGap("lexical","lexical capability unavailable"))
        if PlanOperation.DENSE in ops:nodes.append(PlanNode("dense-0",PlanOperation.DENSE,normalized,"q0",50,domains,variant_key="base"))
        else:gaps.append(PlanGap("dense","dense capability unavailable"))
        if not nodes and self.semantic_planner is not None:self.semantic_calls+=1
        non_exact=[n for n in nodes if n.operation!=PlanOperation.EXACT]
        total=sum(n.candidate_limit for n in nodes)
        if total>budget.max_total_candidates and non_exact:
            room=max(1,budget.max_total_candidates-sum(n.candidate_limit for n in nodes if n.operation==PlanOperation.EXACT))
            per=max(1,room//len(non_exact)); nodes=[replace(n,candidate_limit=min(n.candidate_limit,per)) if n.operation!=PlanOperation.EXACT else n for n in nodes]
        return validate_plan(QueryPlan(query,normalized,intent,scope,snapshot,temporal,budget,features,tuple(nodes),tuple(obligations),tuple(gaps),domains if fallback else (),subquestions))
