#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from cti_rag.evaluation import ExperimentConfig,load_judgments,load_queries,load_runs,run_experiment

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--config",required=True);p.add_argument("--queries",required=True);p.add_argument("--judgments",required=True);p.add_argument("--runs",required=True);p.add_argument("--report",required=True);args=p.parse_args(argv)
    c=json.loads(Path(args.config).read_text(encoding="utf-8"))
    config=ExperimentConfig(
        c["experiment_id"],int(c["seed"]),tuple(c["baselines"]),c["scope_hash"],c["snapshot_id"],int(c["candidate_budget"]),c["resource_condition"],
        tuple(c.get("recall_ks",(20,50,100))),int(c.get("ndcg_k",10)),int(c.get("bootstrap_replicates",1000)),float(c.get("confidence",.95)),int(c.get("min_conclusive_pairs",30)),float(c.get("ndcg_noninferiority_margin",.01)),float(c.get("recall50_noninferiority_margin",.01)),float(c.get("max_p95_latency_ms",5000)),c.get("max_ram_mb"),c.get("max_vram_mb")
    )
    report=run_experiment(config,load_queries(args.queries),load_judgments(args.judgments),load_runs(args.runs))
    Path(args.report).write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8");print(json.dumps({"report":args.report,"digest":report["report_digest"],"runs":sorted(report["runs"])},sort_keys=True))
if __name__=="__main__":raise SystemExit(main())
