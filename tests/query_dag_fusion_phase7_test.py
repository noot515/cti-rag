import asyncio,unittest
from datetime import datetime,timezone

from cti_rag.contracts import AccessLabel,CharacterSpanLocator,PassageHit,ProcessingClass,ProvenanceRef,ScoreDirection,ScoreMetadata,SnapshotManifestRef,TemporalMode,TemporalRequest
from cti_rag.planning import DeterministicQueryPlanner,NodeExecution,PlanBudget,PlanNode,PlanOperation,PlanValidationError,QueryExecution,QueryExecutor,QueryFeatures,QueryIntent,QueryPlan,grouped_rrf,run_b123_fixture,scope_hash,validate_plan
from cti_rag.ports import BackendCapabilities,ChannelResult,ChannelStatus,EffectiveScope,ScoreDirection as PortScoreDirection
from cti_rag.retrieval import ExactLookupResult,ExactLookupStatus

UTC=timezone.utc
NOW=datetime(2026,1,1,tzinfo=UTC)

def scope(domains=("cybersecurity","networking","privacy")):
    return EffectiveScope("alice","public",domains,(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_ONLY,),1,False)
def snapshot(): return SnapshotManifestRef("manifest-1","corpus-1",NOW,("exact-g","lex-g","dense-g"))
def hit(uid,revision="rev",channel="lexical",rank=1):
    prov=ProvenanceRef(revision,CharacterSpanLocator(0,4))
    return PassageHit(f"hit-{channel}-{uid}-{rank}",uid,revision,prov,f"text {uid}",(ScoreMetadata(channel,1.0/rank,ScoreDirection.HIGHER_IS_BETTER,rank,channel),))
def base_plan(nodes,budget=PlanBudget()):
    return QueryPlan("query","query",QueryIntent.EXPLANATION,scope(("cybersecurity",)),snapshot(),TemporalRequest(TemporalMode.CURRENT),budget,QueryFeatures(),tuple(nodes))

class ResultPort:
    capabilities=BackendCapabilities(score_direction=PortScoreDirection.HIGHER_IS_BETTER)
    def __init__(self,result): self.result=result; self.calls=0; self.requests=[]
    async def search(self,request): self.calls+=1; self.requests.append(request); return self.result

class SlowCancelPort:
    capabilities=BackendCapabilities(cancellation=True,score_direction=PortScoreDirection.HIGHER_IS_BETTER)
    def __init__(self): self.started=asyncio.Event(); self.cancelled=False
    async def search(self,request):
        self.started.set()
        try:await asyncio.sleep(10)
        except asyncio.CancelledError:self.cancelled=True;raise
        return ChannelResult(ChannelStatus.EMPTY,reason="unexpected")

class SharedConcurrentPort:
    capabilities=BackendCapabilities(cancellation=True,score_direction=PortScoreDirection.HIGHER_IS_BETTER)
    def __init__(self,state): self.state=state
    async def search(self,request):
        self.state["started"]+=1
        if self.state["started"]>=2:self.state["event"].set()
        await asyncio.wait_for(self.state["event"].wait(),0.5)
        return ChannelResult(ChannelStatus.OK,(hit(request.kind.value+"-p",channel=request.kind.value),))

class DepGraphPort:
    def __init__(self): self.saw_dependency=False
    async def run(self,node,scope_,snapshot_,prior,deadline,cancel_token):
        self.saw_dependency="lex" in prior and prior["lex"].status==ChannelStatus.OK
        return ChannelResult(ChannelStatus.EMPTY,reason="graph fixture empty")

class Phase7PlanningFusionTests(unittest.TestCase):
    def test_exact_identifier_query_uses_no_planner_llm_and_only_exact_route(self):
        planner=DeterministicQueryPlanner(semantic_planner=object())
        plan=planner.compile("CVE-2026-0001",scope(),snapshot(),TemporalRequest(TemporalMode.CURRENT),{PlanOperation.EXACT,PlanOperation.LEXICAL,PlanOperation.DENSE})
        self.assertEqual(plan.intent,QueryIntent.EXACT); self.assertEqual(planner.semantic_calls,0)
        self.assertEqual(tuple(n.operation for n in plan.nodes),(PlanOperation.EXACT,))

    def test_deterministic_feature_extraction_includes_identifiers_dates_and_units(self):
        features=DeterministicQueryPlanner().extract_features("CVE-2026-0001 observed 2026-03-01 with 5 GB")
        self.assertIn(("cve","cve","CVE-2026-0001"),features.identifiers); self.assertIn("2026-03-01",features.dates); self.assertIn("GB",features.units)

    def test_cross_domain_plan_creates_domain_scoped_subquestions(self):
        planner=DeterministicQueryPlanner(); s=scope(("privacy","networking"))
        plan=planner.compile("privacy tracker network dns",s,snapshot(),TemporalRequest(TemporalMode.CURRENT),{PlanOperation.LEXICAL,PlanOperation.DENSE})
        self.assertEqual(plan.intent,QueryIntent.CROSS_DOMAIN); self.assertEqual(len(plan.subquestions),2)
        self.assertEqual({n.subquestion_id for n in plan.nodes},{"q0","q1"}); self.assertTrue(all(len(n.domains)==1 for n in plan.nodes))

    def test_cycle_and_overspending_plans_are_rejected(self):
        n1=PlanNode("a",PlanOperation.LEXICAL,"q","q0",10,("cybersecurity",),("b",))
        n2=PlanNode("b",PlanOperation.DENSE,"q","q0",10,("cybersecurity",),("a",))
        with self.assertRaisesRegex(PlanValidationError,"cyclic"):validate_plan(base_plan((n1,n2)))
        big=PlanNode("big",PlanOperation.LEXICAL,"q","q0",101,("cybersecurity",))
        with self.assertRaisesRegex(PlanValidationError,"candidate budget"):validate_plan(base_plan((big,),PlanBudget(max_total_candidates=100)))

    def test_domain_fallback_never_expands_beyond_authorized_scope(self):
        planner=DeterministicQueryPlanner(); s=scope(("privacy","networking","humanities"))
        plan=planner.compile("explain the ambiguous mechanism",s,snapshot(),TemporalRequest(TemporalMode.CURRENT),{PlanOperation.LEXICAL,PlanOperation.DENSE})
        self.assertTrue(plan.fallback_domains); self.assertLessEqual(len(plan.fallback_domains),2); self.assertTrue(set(plan.fallback_domains).issubset(set(s.domains)))
        for node in plan.nodes:self.assertTrue(set(node.domains).issubset(set(s.domains)))

    def test_unsupported_relation_and_numerical_obligations_are_explicit_gaps(self):
        planner=DeterministicQueryPlanner()
        plan=planner.compile("How many systems are related to CVE-2026-0001?",scope(),snapshot(),TemporalRequest(TemporalMode.CURRENT),{PlanOperation.EXACT,PlanOperation.LEXICAL,PlanOperation.DENSE})
        reasons=" ".join(g.reason for g in plan.gaps)
        self.assertIn("structured capability unavailable",reasons); self.assertIn("graph capability unavailable",reasons)

    def test_independent_lexical_dense_nodes_execute_concurrently(self):
        async def run_case():
            state={"started":0,"event":asyncio.Event()}; ports={"lexical":SharedConcurrentPort(state),"dense":SharedConcurrentPort(state)}
            nodes=(PlanNode("lex",PlanOperation.LEXICAL,"q","q0",5,("cybersecurity",)),PlanNode("dense",PlanOperation.DENSE,"q","q0",5,("cybersecurity",)))
            result=await QueryExecutor(ports,max_concurrency=2).execute(base_plan(nodes))
            return state,result
        state,result=asyncio.run(run_case())
        self.assertEqual(state["started"],2); self.assertTrue(all(n.result.status==ChannelStatus.OK for n in result.nodes))

    def test_dependent_node_waits_for_typed_predecessor(self):
        lex=ResultPort(ChannelResult(ChannelStatus.OK,(hit("p",channel="lexical"),))); graph=DepGraphPort()
        nodes=(PlanNode("lex",PlanOperation.LEXICAL,"q","q0",5,("cybersecurity",)),PlanNode("graph",PlanOperation.GRAPH,"q","q0",5,("cybersecurity",),("lex",)))
        result=asyncio.run(QueryExecutor({"lexical":lex},graph_port=graph).execute(base_plan(nodes)))
        self.assertTrue(graph.saw_dependency); self.assertEqual(len(result.nodes),2)

    def test_cancelling_request_cancels_inflight_supported_work(self):
        async def run_case():
            cancel=asyncio.Event(); lex=SlowCancelPort(); dense=SlowCancelPort()
            nodes=(PlanNode("lex",PlanOperation.LEXICAL,"q","q0",5,("cybersecurity",)),PlanNode("dense",PlanOperation.DENSE,"q","q0",5,("cybersecurity",)))
            task=asyncio.create_task(QueryExecutor({"lexical":lex,"dense":dense},max_concurrency=2).execute(base_plan(nodes),cancel))
            await asyncio.gather(lex.started.wait(),dense.started.wait()); cancel.set(); result=await asyncio.wait_for(task,1.0)
            return lex,dense,result
        lex,dense,result=asyncio.run(run_case())
        self.assertTrue(lex.cancelled and dense.cancelled); self.assertTrue(all(x.result.status==ChannelStatus.REJECTED for x in result.nodes))

    def test_timeout_is_preserved_as_timeout_not_empty(self):
        class TimeoutPort:
            capabilities=BackendCapabilities(cancellation=True)
            async def search(self,request):await asyncio.sleep(0.05);return ChannelResult(ChannelStatus.EMPTY,reason="too late")
        plan=base_plan((PlanNode("lex",PlanOperation.LEXICAL,"q","q0",5,("cybersecurity",)),),PlanBudget(deadline_ms=5))
        execution=asyncio.run(QueryExecutor({"lexical":TimeoutPort()}).execute(plan)); result=execution.nodes[0].result
        self.assertEqual(result.status,ChannelStatus.TIMEOUT); self.assertTrue(any(g.obligation=="lexical" and "deadline" in g.reason for g in execution.gaps))

    def test_fixed_ranks_produce_known_equal_weight_rrf_values(self):
        lex=NodeExecution(PlanNode("lex",PlanOperation.LEXICAL,"q","q0",5,("cybersecurity",)),ChannelResult(ChannelStatus.OK,(hit("p",channel="lexical",rank=1),hit("x",channel="lexical",rank=2))))
        dense=NodeExecution(PlanNode("dense",PlanOperation.DENSE,"q","q0",5,("cybersecurity",)),ChannelResult(ChannelStatus.OK,(hit("y",channel="dense",rank=1),hit("p",channel="dense",rank=2))))
        fused=grouped_rrf(QueryExecution("plan",(lex,dense),(),NOW,NOW),k=60,top_k=10); p=next(v for v in fused.passages if v.passage.passage_uid=="p")
        self.assertAlmostEqual(p.score,1/61+1/62); self.assertEqual(dict(p.channel_ranks),{"dense":2,"lexical":1})

    def test_fusion_round_robins_across_subquestions_for_coverage(self):
        q0=NodeExecution(PlanNode("q0-lex",PlanOperation.LEXICAL,"q","q0",5,("cybersecurity",)),ChannelResult(ChannelStatus.OK,(hit("a",channel="lexical",rank=1),hit("b",channel="lexical",rank=2),hit("c",channel="lexical",rank=3))))
        q1=NodeExecution(PlanNode("q1-lex",PlanOperation.LEXICAL,"q","q1",5,("networking",)),ChannelResult(ChannelStatus.OK,(hit("z",channel="lexical",rank=1),)))
        fused=grouped_rrf(QueryExecution("coverage",(q0,q1),(),NOW,NOW),top_k=2)
        self.assertEqual(tuple(row.subquestion_id for row in fused.passages),("q0","q1"))

    def test_repeating_same_query_variant_does_not_create_extra_fusion_votes(self):
        node1=PlanNode("lex-a",PlanOperation.LEXICAL,"rewrite","q0",5,("cybersecurity",),variant_key="same-rewrite")
        node2=PlanNode("lex-b",PlanOperation.LEXICAL,"rewrite","q0",5,("cybersecurity",),variant_key="same-rewrite")
        result=ChannelResult(ChannelStatus.OK,(hit("p",channel="lexical",rank=1),))
        one=grouped_rrf(QueryExecution("p1",(NodeExecution(node1,result),),(),NOW,NOW),top_k=5)
        two=grouped_rrf(QueryExecution("p2",(NodeExecution(node1,result),NodeExecution(node2,result)),(),NOW,NOW),top_k=5)
        self.assertEqual(one.passages[0].score,two.passages[0].score)

    def test_high_similarity_wrong_id_passage_cannot_replace_exact_obligation(self):
        exact=NodeExecution(PlanNode("exact",PlanOperation.EXACT,"CVE-2026-0001","q0",1,("cybersecurity",),required=True),ExactLookupResult(ExactLookupStatus.FOUND,(),None))
        dense=NodeExecution(PlanNode("dense",PlanOperation.DENSE,"CVE-2026-0001","q0",5,("cybersecurity",)),ChannelResult(ChannelStatus.OK,(hit("wrong-id",channel="dense",rank=1),)))
        fused=grouped_rrf(QueryExecution("plan",(exact,dense),(),NOW,NOW),top_k=5)
        self.assertEqual(len(fused.exact_obligations),1); self.assertEqual(fused.exact_obligations[0].status,ExactLookupStatus.FOUND); self.assertEqual(fused.passages[0].passage.passage_uid,"wrong-id")

    def test_minimal_b1_b2_b3_fixture_uses_identical_scope_and_snapshot_controls(self):
        sh=scope_hash(scope(("cybersecurity",))); rows=run_b123_fixture(scope_hash=sh,snapshot_id=snapshot().manifest_id,relevant=("p1",),exact_ranking=("p1",),lexical_ranking=("p2","p1"),fused_ranking=("p1","p2"),k=2)
        self.assertEqual([r.name for r in rows],["B1-exact","B2-lexical","B3-grouped-fusion"]); self.assertEqual({r.scope_hash for r in rows},{sh}); self.assertEqual({r.snapshot_id for r in rows},{snapshot().manifest_id}); self.assertTrue(all(not r.semantic_quality_claim for r in rows))

if __name__=="__main__":unittest.main()
