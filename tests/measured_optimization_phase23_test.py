from __future__ import annotations
import json,subprocess,sys,tempfile,unittest
from dataclasses import dataclass
from pathlib import Path

from cti_rag.context import EvidenceHydrator,PassageMetadata
from cti_rag.contracts import AccessLabel,JsonPointerLocator,PassageHit,PolicyLabels,ProcessingClass,ProvenanceRef
from cti_rag.optimization import load_grid,load_observations,select_optimization
from cti_rag.planning import DeterministicQueryPlanner,FusedPassage,PlanOperation
from cti_rag.ports import EffectiveScope

ROOT=Path(__file__).resolve().parents[1]
GRID=ROOT/"evaluation"/"phase23"/"optimization-grid.json"
OBS=ROOT/"evaluation"/"phase23"/"fixture-observations.json"

@dataclass(frozen=True)
class CanonicalPassage:
    revision_uid:str
    provenance:object
    text:str

class PointStore:
    def __init__(self,rows):self.rows=rows;self.point_calls=0
    def get_passage(self,uid):self.point_calls+=1;return self.rows.get(uid)

class BulkStore(PointStore):
    def __init__(self,rows):super().__init__(rows);self.bulk_calls=0
    def get_passages(self,uids):self.bulk_calls+=1;return {uid:self.rows.get(uid) for uid in uids}

class PointMetadata:
    def __init__(self,rows):self.rows=rows;self.point_calls=0
    def get(self,uid):self.point_calls+=1;return self.rows.get(uid)

class BulkMetadata(PointMetadata):
    def __init__(self,rows):super().__init__(rows);self.bulk_calls=0
    def get_many(self,uids):self.bulk_calls+=1;return {uid:self.rows.get(uid) for uid in uids}

class Phase23MeasuredOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.scope=EffectiveScope("p","public",("cybersecurity",),(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_ONLY,),1)
        self.snapshot=type("S",(),{"manifest_id":"m1"})()
        self.fused=[];self.canonical={};self.metadata={}
        labels=PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY)
        for i in range(40):
            uid=f"p{i}";rev=f"r{i}";prov=ProvenanceRef(rev,JsonPointerLocator("/text"));text=f"evidence {i}"
            hit=PassageHit(f"h{i}",uid,rev,prov,text)
            self.fused.append(FusedPassage(hit,1.0/(i+1),(("lexical",i+1),),"q0"))
            self.canonical[uid]=CanonicalPassage(rev,prov,text)
            self.metadata[uid]=PassageMetadata(labels,"fixture",f"origin-{i}","m1")

    def test_profiled_bulk_hydration_removes_n_plus_one_reads_without_changing_evidence(self):
        point_store=PointStore(self.canonical);point_meta=PointMetadata(self.metadata)
        point=EvidenceHydrator(point_store,point_meta,enable_bulk=False)
        p_rows,p_denied,p_invalid,p_profile=point.hydrate_profiled(self.fused,self.scope,self.snapshot)
        bulk_store=BulkStore(self.canonical);bulk_meta=BulkMetadata(self.metadata)
        bulk=EvidenceHydrator(bulk_store,bulk_meta,enable_bulk=True,max_batch_size=16)
        b_rows,b_denied,b_invalid,b_profile=bulk.hydrate_profiled(self.fused,self.scope,self.snapshot)
        self.assertEqual(tuple(v.passage.passage_uid for v in p_rows),tuple(v.passage.passage_uid for v in b_rows))
        self.assertEqual((0,0),(p_denied,p_invalid));self.assertEqual((0,0),(b_denied,b_invalid))
        self.assertEqual((40,40),(p_profile.evidence_backend_calls,p_profile.metadata_backend_calls))
        self.assertEqual((3,3),(b_profile.evidence_backend_calls,b_profile.metadata_backend_calls))
        self.assertTrue(b_profile.bulk_evidence_used);self.assertTrue(b_profile.bulk_metadata_used)
        self.assertEqual((40,40),(point_store.point_calls,point_meta.point_calls))

    def test_bulk_hydration_is_opt_in_and_point_contract_remains_rollback_path(self):
        store=BulkStore(self.canonical);meta=BulkMetadata(self.metadata)
        hydrator=EvidenceHydrator(store,meta)
        _rows,_denied,_invalid,profile=hydrator.hydrate_profiled(self.fused[:4],self.scope,self.snapshot)
        self.assertFalse(profile.bulk_evidence_used);self.assertFalse(profile.bulk_metadata_used)
        self.assertEqual((4,4),(profile.evidence_backend_calls,profile.metadata_backend_calls))

    def test_exact_identifier_path_skips_text_and_semantic_planning(self):
        planner=DeterministicQueryPlanner(semantic_planner=object())
        temporal=type("T",(),{})();snapshot=type("R",(),{"manifest_id":"m1"})()
        plan=planner.compile("CVE-2026-1234",self.scope,snapshot,temporal,{PlanOperation.EXACT,PlanOperation.LEXICAL,PlanOperation.DENSE})
        self.assertEqual(0,planner.semantic_calls);self.assertEqual((PlanOperation.EXACT,),tuple(n.operation for n in plan.nodes))

    def test_frozen_sweep_varies_every_required_axis_and_rejects_bad_candidates(self):
        plan,configs,raw=load_grid(GRID);observations=load_observations(OBS)
        required=("passage_tokens","overlap_tokens","context_prefix_mode","analyzer","lexical_window","dense_window","ann_probe","rerank_candidates","context_tokens","graph_cap","routing_fallback_domains","bulk_hydration")
        for axis in required:self.assertGreater(len({getattr(c,axis) for c in configs}),1,axis)
        decision=select_optimization(plan,configs,observations);by_id={v.config_id:v for v in decision.candidates}
        self.assertEqual("bulk-hydration-32",decision.tuning_choice)
        self.assertEqual("baseline-v1",decision.production_choice)
        self.assertEqual("blocked",decision.status);self.assertTrue(decision.holdout_evaluated)
        self.assertIn("recall50_noninferiority",by_id["lexical-window-20"].reasons)
        self.assertIn("ann_recall_noninferiority",by_id["ann-probe-8"].reasons)
        self.assertIn("graph_recall_noninferiority",by_id["text-only"].reasons)
        heldout={o.config_id for o in observations if o.split=="holdout"}
        self.assertEqual({"baseline-v1","bulk-hydration-32"},heldout)
        self.assertEqual(130,raw["partition_counts"]["tuning"]);self.assertEqual(150,raw["partition_counts"]["holdout"])
        self.assertFalse(set(raw["tuning_query_splits"]) & set(raw["holdout_query_splits"]))

    def test_optimization_cli_keeps_production_baseline_without_real_runtime_claim(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"report.json"
            proc=subprocess.run([sys.executable,str(ROOT/"scripts"/"run_phase23_optimization.py"),"--grid",str(GRID),"--observations",str(OBS),"--report",str(out)],cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(0,proc.returncode,proc.stderr);report=json.loads(out.read_text())
            self.assertEqual("bulk-hydration-32",report["decision"]["tuning_choice"])
            self.assertEqual("baseline-v1",report["decision"]["production_choice"])
            self.assertFalse(report["performance_claim_allowed"]);self.assertEqual(2,len(report["slice_evidence"]))
            self.assertIn("cybersecurity",report["slice_evidence"][0]["domains"])
            selected=json.loads((ROOT/"config"/"retrieval-optimization-selected.json").read_text())
            self.assertEqual(report["decision"]["production_choice"],selected["config_id"])

if __name__=="__main__":unittest.main()
