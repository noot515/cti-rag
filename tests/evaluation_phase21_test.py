from __future__ import annotations
from dataclasses import replace
import json,subprocess,sys,tempfile,unittest
from pathlib import Path

from cti_rag.evaluation import (
    BASELINE_DEFINITIONS,EvaluationQuery,EvaluationRun,ExperimentConfig,JudgmentStatus,
    ModelExecutionKind,QueryOutcome,RelevanceJudgment,RunMetadata,
    hard_failure_counts,load_judgments,load_queries,load_runs,paired_bootstrap,run_experiment,
)

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"evaluation"/"phase21"/"dev-v1"

def config():
    row=json.loads((DATA/"experiment-config.json").read_text())
    return ExperimentConfig(
        row["experiment_id"],row["seed"],tuple(row["baselines"]),row["scope_hash"],row["snapshot_id"],row["candidate_budget"],row["resource_condition"],
        tuple(row["recall_ks"]),row["ndcg_k"],row["bootstrap_replicates"],row["confidence"],row["min_conclusive_pairs"],
        row["ndcg_noninferiority_margin"],row["recall50_noninferiority_margin"],row["max_p95_latency_ms"],row["max_ram_mb"],row["max_vram_mb"],
    )

class Phase21EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queries=load_queries(DATA/"queries.jsonl");cls.judgments=load_judgments(DATA/"judgments.jsonl");cls.runs=load_runs(DATA/"fixture-runs.json")

    def test_dataset_counts_labels_and_duplicate_split_integrity(self):
        self.assertEqual(270,len(self.queries));self.assertEqual(270,len(self.judgments))
        for domain in ("cybersecurity","networking","quant","humanities","privacy"):
            self.assertEqual(50,sum(q.domain==domain and q.split!="adversarial" for q in self.queries))
        self.assertEqual(250,sum(j.status==JudgmentStatus.MACHINE_GENERATED_UNREVIEWED for j in self.judgments))
        self.assertEqual(20,sum(j.status==JudgmentStatus.SYNTHETIC_CONTRACT for j in self.judgments))
        self.assertEqual(0,sum(j.status==JudgmentStatus.HUMAN_REVIEWED for j in self.judgments))
        groups={}
        for q in self.queries:
            if q.split=="adversarial":continue
            groups.setdefault(q.duplicate_group,set()).add(q.split)
        self.assertTrue(all(len(v)==1 for v in groups.values()))

    def test_b0_through_b8_are_explicit_and_conditions_are_equal(self):
        self.assertEqual(tuple(f"B{i}" for i in range(9)),tuple(BASELINE_DEFINITIONS))
        report=run_experiment(config(),self.queries,self.judgments,self.runs)
        self.assertEqual({"B0","B8"},set(report["runs"]))
        self.assertEqual(config().scope_hash,report["runs"]["B0"]["metadata"]["scope_hash"])
        bad=EvaluationRun(replace(self.runs[0].metadata,candidate_budget=config().candidate_budget+1),self.runs[0].outcomes)
        with self.assertRaisesRegex(ValueError,"conditions differ"):run_experiment(config(),self.queries,self.judgments,(bad,))

    def test_frozen_experiment_is_reproducible_and_fake_models_never_claim_quality(self):
        a=run_experiment(config(),self.queries,self.judgments,self.runs)
        b=run_experiment(config(),self.queries,self.judgments,self.runs)
        self.assertEqual(a["report_digest"],b["report_digest"])
        for run in a["runs"].values():
            self.assertEqual("not_run_fake_or_no_model",run["semantic_model_metrics_status"])
            self.assertEqual({},run["semantic_model_metrics"])
        self.assertTrue(a["paired_comparisons"]["B0->B8"]["ndcg@10"]["conclusive"])
        self.assertTrue(a["paired_comparisons"]["B0->B8"]["ndcg@10"]["noninferior"])

    def test_underpowered_bootstrap_is_explicitly_inconclusive(self):
        result=paired_bootstrap([1,1,1],[1,1,0],replicates=200,seed=7,min_pairs=30,noninferiority_margin=.01)
        self.assertFalse(result["conclusive"]);self.assertFalse(result["noninferior"]);self.assertIsNotNone(result["ci_low"])

    def test_seeded_failure_modes_are_detected_by_separate_hard_metrics(self):
        queries=(
            EvaluationQuery("router","cybersecurity","q","routing","f","g1","adversarial","current",True,("dense",),("q0",),("seed_bad_router",)),
            EvaluationQuery("future","quant","q","historical","f","g2","adversarial","historical",True,("lexical",),("q0",),("future_revision_leak",)),
            EvaluationQuery("dup","privacy","q","duplicate","f","g3","adversarial","current",True,("lexical",),("q0",),("duplicate_source_boost",)),
            EvaluationQuery("number","quant","q","structured","f","g4","adversarial","current",True,("structured",),("q0",),("wrong_numerical_result",)),
            EvaluationQuery("citation","humanities","q","citation","f","g5","adversarial","current",True,("lexical",),("q0",),("unsupported_citation",)),
        )
        judgments=tuple(RelevanceJudgment(q.query_id,JudgmentStatus.SYNTHETIC_CONTRACT,((f"u:{q.query_id}",2),),expected_structured=(("v","42","u"),) if q.query_id=="number" else ()) for q in queries)
        outcomes=(
            QueryOutcome("router",("u:router",),("o1",),(),covered_subquestions=("q0",)),
            QueryOutcome("future",("u:future",),("o2",),("lexical",),covered_subquestions=("q0",),temporal_failure=True),
            QueryOutcome("dup",("u:dup","x"),("same","same"),("lexical",),covered_subquestions=("q0",)),
            QueryOutcome("number",("u:number",),("o4",),("structured",),covered_subquestions=("q0",),structured_values=(("v","41","u"),)),
            QueryOutcome("citation",("u:citation",),("o5",),("lexical",),covered_subquestions=("q0",),citations=(("u:citation",False),)),
        )
        failures=hard_failure_counts(queries,judgments,outcomes)
        self.assertEqual(1,failures["router_miss"]);self.assertEqual(1,failures["future_revision_leak"])
        self.assertEqual(1,failures["duplicate_source_boost"]);self.assertEqual(1,failures["wrong_structured_result"])
        self.assertEqual(1,failures["unsupported_citation"])

    def test_real_model_run_requires_fingerprint(self):
        with self.assertRaises(ValueError):
            RunMetadata("B4","scope","snap",100,"gpu",ModelExecutionKind.REAL_MODEL)

    def test_cli_writes_same_report_digest(self):
        expected=run_experiment(config(),self.queries,self.judgments,self.runs)["report_digest"]
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"report.json"
            proc=subprocess.run([sys.executable,str(ROOT/"scripts"/"run_phase21_evaluation.py"),"--config",str(DATA/"experiment-config.json"),"--queries",str(DATA/"queries.jsonl"),"--judgments",str(DATA/"judgments.jsonl"),"--runs",str(DATA/"fixture-runs.json"),"--report",str(out)],cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(0,proc.returncode,proc.stderr)
            self.assertEqual(expected,json.loads(out.read_text())["report_digest"])

if __name__=="__main__":unittest.main()
