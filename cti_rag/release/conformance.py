"""Release conformance matrix and source-readiness validation."""
from __future__ import annotations
import json
from pathlib import Path

VALID_STATUSES=frozenset(("passed","failed","blocked","not_run"))
VALID_GROUPS=frozenset(("foundation","text_mvp","five_domain","optional_integration","deferred_research","release"))

def load_requirement_matrix(path,root=None):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version")!="revised-plan-conformance/1":raise ValueError("unsupported conformance matrix schema")
    sections=data.get("sections",())
    numbers=[int(row["section"]) for row in sections]
    if sorted(numbers)!=list(range(1,26)) or len(numbers)!=len(set(numbers)):raise ValueError("conformance matrix must account for revised-plan sections 1 through 25 exactly once")
    ids=set()
    for section in sections:
        requirements=section.get("requirements",())
        if not requirements:raise ValueError(f"section {section['section']} has no mapped requirements")
        for req in requirements:
            rid=str(req["id"])
            if rid in ids:raise ValueError("duplicate conformance requirement id")
            ids.add(rid)
            if req["status"] not in VALID_STATUSES:raise ValueError("invalid conformance status")
            if req["group"] not in VALID_GROUPS:raise ValueError("invalid conformance group")
            if not req.get("code_refs") or not req.get("test_refs"):raise ValueError("requirement needs code and test/status evidence refs")
            if root is not None:
                root=Path(root)
                for ref in tuple(req["code_refs"])+tuple(req["test_refs"]):
                    if not (root/ref).exists():raise ValueError(f"conformance reference does not exist: {ref}")
    return data

def milestone_readiness(matrix,milestone):
    required=tuple(matrix.get("milestone_requirements",{}).get(milestone,()))
    by_id={req["id"]:req for section in matrix["sections"] for req in section["requirements"]}
    missing=[rid for rid in required if rid not in by_id]
    if missing:raise ValueError("milestone references unknown requirements: "+",".join(missing))
    blocking=[rid for rid in required if by_id[rid]["status"]!="passed"]
    return {"milestone":milestone,"status":"passed" if not blocking else "blocked","blocking_requirements":blocking}

def load_source_readiness(path):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version")!="source-readiness/1":raise ValueError("unsupported source readiness schema")
    seen=set()
    for row in data.get("sources",()):
        sid=row["source_id"]
        if sid in seen:raise ValueError("duplicate source readiness id")
        seen.add(sid)
        for field in ("manifest_status","adapter_status","fixture_lifecycle","live_lifecycle"):
            if row[field] not in VALID_STATUSES:raise ValueError(f"invalid source status: {field}")
        if row["live_lifecycle"]=="passed" and (row["adapter_status"]!="passed" or row["fixture_lifecycle"]!="passed"):
            raise ValueError("live source readiness requires an implemented adapter and fixture lifecycle")
        if row["manifest_status"]=="passed" and row["adapter_status"]!="passed" and not row.get("notes"):
            raise ValueError("manifest-only sources must explain the adapter gap")
    return data
