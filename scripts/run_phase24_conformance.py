#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from cti_rag.release import load_requirement_matrix,load_source_readiness,milestone_readiness

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--matrix",default="validation/revised-plan-conformance.json");p.add_argument("--sources",default="validation/source-readiness.json");p.add_argument("--report",required=True);args=p.parse_args(argv)
    matrix=load_requirement_matrix(ROOT/args.matrix,ROOT);sources=load_source_readiness(ROOT/args.sources)
    milestones={name:milestone_readiness(matrix,name) for name in matrix["milestone_requirements"]}
    report={"schema_version":"phase24-conformance-report/1","sections_accounted":len(matrix["sections"]),"source_count":len(sources["sources"]),"milestones":milestones,"sources":sources}
    Path(args.report).write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":args.report,"sections":len(matrix["sections"]),"milestones":milestones},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(main())
