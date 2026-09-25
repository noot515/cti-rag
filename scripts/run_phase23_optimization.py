#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,sys
from dataclasses import asdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from cti_rag.optimization import load_grid,load_observations,select_optimization

REQUIRED_AXES=("passage_tokens","overlap_tokens","context_prefix_mode","analyzer","lexical_window","dense_window","ann_probe","rerank_candidates","context_tokens","graph_cap","routing_fallback_domains","bulk_hydration")

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--grid",required=True);p.add_argument("--observations",required=True);p.add_argument("--report",required=True);args=p.parse_args(argv)
    plan,configs,raw=load_grid(args.grid);observations=load_observations(args.observations)
    baseline=next(c for c in configs if c.config_id==plan.baseline_config_id)
    swept={axis:sorted({getattr(c,axis) for c in configs},key=str) for axis in REQUIRED_AXES}
    missing=[axis for axis,values in swept.items() if len(values)<2]
    if missing:raise SystemExit("required sweep axes are not varied: "+",".join(missing))
    decision=select_optimization(plan,configs,observations)
    config_map={c.config_id:c for c in configs}
    selected=config_map[decision.tuning_choice]
    report={
        "schema_version":"phase23-optimization-report/1","plan":asdict(plan),"swept_axes":swept,
        "decision":asdict(decision),"tuning_choice_config":asdict(selected),"production_choice_config":asdict(config_map[decision.production_choice]),
        "tradeoffs":{"dependencies":selected.dependencies,"semantic_risks":selected.semantic_risks},
        "input_fingerprints":{
            "grid":hashlib.sha256(Path(args.grid).read_bytes()).hexdigest(),
            "observations":hashlib.sha256(Path(args.observations).read_bytes()).hexdigest(),
        },
        "performance_claim_allowed":decision.status=="passed" and decision.production_choice!=plan.baseline_config_id,
    }
    encoded=json.dumps(report,sort_keys=True,indent=2)+"\n";Path(args.report).write_text(encoded,encoding="utf-8")
    print(json.dumps({"status":decision.status,"tuning_choice":decision.tuning_choice,"production_choice":decision.production_choice,"performance_claim_allowed":report["performance_claim_allowed"],"report":args.report},sort_keys=True))
    return 0 if decision.status in ("passed","blocked") else 1
if __name__=="__main__":raise SystemExit(main())
