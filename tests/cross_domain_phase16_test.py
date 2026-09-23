import asyncio,tempfile,unittest
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path

from cti_rag.context import ContextBudget,ContextPacker,EvidencePassage,RerankOutcome,RerankedPassage
from cti_rag.contracts import (
    AccessLabel,CharacterSpanLocator,PassageHit,PolicyLabels,ProcessingClass,ProvenanceRef,
    ScoreDirection,ScoreMetadata,SnapshotManifestRef,TemporalMode,TemporalRequest,
)
from cti_rag.domains.networking import BGP_FIXTURE,BGP_MANIFEST,BgpConnector,BgpNormalizer,NetworkingProjectionRebuilder
from cti_rag.domains.quant import (
    PRICE_ADJUSTED_CSV_FIXTURE,PRICE_CSV_FIXTURE,PRICE_MANIFEST,SEC_MANIFEST,SECURITY_MASTER_MANIFEST,
    EventStudySpec,PriceFileConnector,PriceNormalizer,QuantCalculationEngine,QuantProjectionRebuilder,
    SecConnector,SecNormalizer,SecurityMasterConnector,SecurityMasterNormalizer,quant_dataset_registry,
)
from cti_rag.graph import EntityResolutionJournal,ReferenceGraphPort,TraversalStep,TraversalTemplate
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
from cti_rag.ingestion import IngestionPipeline
from cti_rag.planning import (
    BENCHMARK_SECURITY,EVENT_DATE,ISSUER_NETWORK_TEMPLATE,ISSUER_SECURITY_TEMPLATE,NETWORK_GRAPH_TEMPLATE,RETURN_CALC_TEMPLATE,
    CoverageStatus,CrossDomainCoordinator,JoinedCalculationPort,JoinedGraphPort,NodeExecution,PlanBudget,PlanNode,PlanOperation,
    PlanValidationError,QueryExecution,QueryFeatures,QueryIntent,QueryPlan,Subquestion,TypedJoinPort,
    TypedJoinStatus,incident_join_records,incident_market_plan,grouped_rrf,
)
from cti_rag.ports import ChannelResult,ChannelStatus,EffectiveScope,ProjectionBuildRequest
from cti_rag.retrieval import PersistentExactIndex,SQLiteFTS5LexicalIndex
from cti_rag.snapshots import SnapshotCatalogStore,SnapshotPublisher
from cti_rag.structured import DuckDBStructuredPort

UTC=timezone.utc
NOW=datetime(2026,3,1,tzinfo=UTC)
SCOPE=EffectiveScope("alice","public",("quant","networking"),(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_ONLY,),1)

async def ingest_all(pipeline):
    cursor=None
    while True:
        result=await pipeline.ingest_page(cursor)
        if result["exhausted"]:return result
        cursor=result["next_cursor"]

class SupportStore:
    def __init__(self,revisions,text_by_revision=None):
        self.revisions=set(revisions);self.text_by_revision=dict(text_by_revision or {})
    def resolve(self,ref):
        if ref.revision_uid not in self.revisions:return None
        return self.text_by_revision.get(ref.revision_uid,b"supported")
    def get_revision(self,uid):return None
    def get_artifact(self,uid):return None
    def get_passage(self,uid):return None
    def dependents(self,uid):return ()

class EmptyLexical:
    def __init__(self,capabilities):self.capabilities=capabilities
    async def search(self,request):return ChannelResult(ChannelStatus.EMPTY,reason="required disclosure source removed")

def runtime(td):
    root=Path(td);objects=FileObjectStore(root/"objects");meta=CanonicalMetadataStore.sqlite(root/"meta.db",object_exists=objects.exists);catalog=SnapshotCatalogStore.sqlite(root/"catalog.db")
    return objects,meta,catalog

def build_cross_domain(td,records):
    objects,meta,catalog=runtime(td)
    jobs=(
      (SEC_MANIFEST,SecConnector(),SecNormalizer()),
      (PRICE_MANIFEST,PriceFileConnector(PRICE_CSV_FIXTURE),PriceNormalizer()),
      (PRICE_MANIFEST,PriceFileConnector(PRICE_ADJUSTED_CSV_FIXTURE),PriceNormalizer()),
      (SECURITY_MASTER_MANIFEST,SecurityMasterConnector(),SecurityMasterNormalizer()),
      (BGP_MANIFEST,BgpConnector(BGP_FIXTURE[:3]),BgpNormalizer()),
    )
    for manifest,connector,normalizer in jobs:
        result=asyncio.run(ingest_all(IngestionPipeline(manifest,connector,normalizer,objects,meta)))
        assert result["quarantined"]==0
    quant=QuantProjectionRebuilder(meta,objects).rebuild((SEC_MANIFEST.source_id,PRICE_MANIFEST.source_id,SECURITY_MASTER_MANIFEST.source_id),"cross-manifest")
    network=NetworkingProjectionRebuilder(meta,objects).rebuild((BGP_MANIFEST.source_id,),"cross-manifest")
    join_revs={p.revision_uid for row in records for p in row.support}
    all_revs=tuple(sorted({x.revision_uid for x in quant.exact}|{x.revision_uid for x in quant.lexical}|{a.revision_uid for a in network.assertions}|join_revs))
    exact=PersistentExactIndex.sqlite(Path(td)/"exact.db",catalog)
    lex=SQLiteFTS5LexicalIndex(Path(td)/"lex.db",catalog)
    eg=exact.build(ProjectionBuildRequest("cross-exact","exact",all_revs,("canonical/1",),("exact",)),quant.exact)
    lg=lex.build(ProjectionBuildRequest("cross-lex","lexical",all_revs,("unicode61/1",),("lexical",)),quant.lexical)
    support=SupportStore(all_revs)
    template=TraversalTemplate("network-relations",(TraversalStep("announced_by",("prefix",),("asn",)),))
    graph=ReferenceGraphPort(catalog,support,(template,),EntityResolutionJournal(network.entities))
    gg=graph.build(ProjectionBuildRequest("cross-graph","graph",all_revs,("graph/1",),("graph",)),network.entities,network.assertions)
    pub=SnapshotPublisher(catalog)
    for generation in (eg,lg,gg):pub.stage_generation(generation)
    manifest=pub.publish(("cross-exact","cross-lex","cross-graph"),("exact","lexical","graph"),created_at=NOW)
    snap=manifest.to_ref()
    join=TypedJoinPort((ISSUER_NETWORK_TEMPLATE,ISSUER_SECURITY_TEMPLATE),records,catalog,support)
    joined_graph=JoinedGraphPort(graph,(NETWORK_GRAPH_TEMPLATE,))
    structured=DuckDBStructuredPort(quant_dataset_registry(quant.structured_rows))
    engine=QuantCalculationEngine(structured)
    async def event_study(key,scope,snapshot,temporal):
        return await engine.event_study(EventStudySpec(key.identifier,BENCHMARK_SECURITY,EVENT_DATE),scope,temporal,snapshot)
    calc=JoinedCalculationPort((RETURN_CALC_TEMPLATE,),{"event-study":event_study})
    from cti_rag.planning import QueryExecutor
    executor=QueryExecutor({"lexical":lex},exact_index=exact,graph_port=joined_graph,structured_port=calc,join_port=join,max_concurrency=4)
    plan=incident_market_plan(SCOPE,snap)
    return {"catalog":catalog,"snapshot":snap,"exact":exact,"lex":lex,"graph":joined_graph,"calc":calc,"join":join,"executor":executor,"plan":plan}

def fields(result):
    return {f.name:f.value for f in result.fields}

class WordTokenizer:
    name="word";revision="1"
    def encode(self,text):return tuple(range(len(text.split())))
    def decode(self,tokens):return " ".join("x" for _ in tokens)
    @property
    def fingerprint(self):return "word/1"

class TextStore:
    def __init__(self,items):self.items=items
    def resolve(self,ref):return self.items.get(ref.revision_uid)

def passage(uid,rev,text,channel,rank):
    loc=CharacterSpanLocator(0,len(text))
    return PassageHit("hit-"+uid,uid,rev,ProvenanceRef(rev,loc),text,(ScoreMetadata(channel,1.0/rank,ScoreDirection.HIGHER_IS_BETTER,rank,channel),))

class Phase16CrossDomainTests(unittest.TestCase):
    def test_complete_fixture_uses_four_modalities_with_citations_and_numeric_ground_truth(self):
        with tempfile.TemporaryDirectory() as td:
            env=build_cross_domain(td,incident_join_records())
            outcome=asyncio.run(CrossDomainCoordinator().execute(env["plan"],env["executor"]))
            self.assertEqual(outcome.status,"complete")
            self.assertEqual({x.status for x in outcome.coverage},{CoverageStatus.SATISFIED})
            self.assertTrue(all(x.citation_count>0 for x in outcome.coverage))
            operations={item.node.operation for item in outcome.execution.nodes}
            self.assertTrue({PlanOperation.EXACT,PlanOperation.LEXICAL,PlanOperation.JOIN,PlanOperation.GRAPH,PlanOperation.STRUCTURED}.issubset(operations))
            njoin=outcome.execution.result_for("network-join")
            self.assertEqual(njoin.status,TypedJoinStatus.RESOLVED);self.assertEqual(njoin.selected.identifier,"203.0.113.0/24")
            self.assertIn("198.51.100.0/24",{x.identifier for x in njoin.suggestions})
            sjoin=outcome.execution.result_for("security-join");self.assertEqual(sjoin.status,TypedJoinStatus.RESOLVED);self.assertEqual(sjoin.selected.identifier,"SEC-EXAMPLE")
            route=outcome.execution.result_for("network-route");self.assertEqual(route.status,ChannelStatus.OK);self.assertTrue(all(x.provenances for x in route.items))
            calc=outcome.execution.result_for("abnormal-return");self.assertEqual(calc.status,ChannelStatus.OK)
            result=calc.items[0];self.assertAlmostEqual(fields(result)["cumulative_abnormal_return"],0.03,places=12)
            self.assertIn("not a causal or profitability claim",fields(result)["association_label"])
            self.assertTrue(outcome.trace.calculation_lineage);self.assertTrue(outcome.trace.join_decisions)
            self.assertIn("does not by itself establish causal attribution",outcome.claim_scope_note)

    def test_ambiguous_security_join_returns_partial_and_never_runs_calculation(self):
        with tempfile.TemporaryDirectory() as td:
            env=build_cross_domain(td,incident_join_records(ambiguous_security=True))
            outcome=asyncio.run(CrossDomainCoordinator().execute(env["plan"],env["executor"]))
            self.assertEqual(outcome.status,"partial")
            join=outcome.execution.result_for("security-join");self.assertEqual(join.status,TypedJoinStatus.AMBIGUOUS);self.assertIsNone(join.selected);self.assertEqual(len(join.candidates),2)
            calc=outcome.execution.result_for("abnormal-return")
            self.assertEqual(calc.status,ChannelStatus.REJECTED);self.assertIn("typed join dependency unresolved",calc.reason)
            coverage={x.obligation_id:x for x in outcome.coverage}
            self.assertEqual(coverage["security-join"].status,CoverageStatus.PARTIAL);self.assertEqual(coverage["abnormal-return"].status,CoverageStatus.FAILED)

    def test_time_incompatible_network_relation_cannot_bridge_to_graph(self):
        with tempfile.TemporaryDirectory() as td:
            env=build_cross_domain(td,incident_join_records(time_incompatible_network=True))
            outcome=asyncio.run(CrossDomainCoordinator().execute(env["plan"],env["executor"]))
            join=outcome.execution.result_for("network-join");self.assertEqual(join.status,TypedJoinStatus.TIME_INCOMPATIBLE);self.assertIsNone(join.selected)
            graph=outcome.execution.result_for("network-route");self.assertEqual(graph.status,ChannelStatus.REJECTED)
            self.assertEqual(outcome.status,"partial")

    def test_missing_price_variant_resolves_identity_but_marks_numeric_obligation_missing(self):
        with tempfile.TemporaryDirectory() as td:
            env=build_cross_domain(td,incident_join_records(missing_price_security=True))
            outcome=asyncio.run(CrossDomainCoordinator().execute(env["plan"],env["executor"]))
            join=outcome.execution.result_for("security-join");self.assertEqual(join.status,TypedJoinStatus.RESOLVED);self.assertEqual(join.selected.identifier,"SEC-NO-PRICE")
            calc=outcome.execution.result_for("abnormal-return");self.assertEqual(calc.status,ChannelStatus.EMPTY)
            coverage={x.obligation_id:x for x in outcome.coverage}
            self.assertEqual(coverage["abnormal-return"].status,CoverageStatus.MISSING);self.assertEqual(outcome.status,"partial")

    def test_removing_required_disclosure_source_changes_completeness(self):
        with tempfile.TemporaryDirectory() as td:
            env=build_cross_domain(td,incident_join_records())
            from cti_rag.planning import QueryExecutor
            executor=QueryExecutor({"lexical":EmptyLexical(env["lex"].capabilities)},exact_index=env["exact"],graph_port=env["graph"],structured_port=env["calc"],join_port=env["join"],max_concurrency=4)
            outcome=asyncio.run(CrossDomainCoordinator().execute(env["plan"],executor))
            coverage={x.obligation_id:x for x in outcome.coverage}
            self.assertEqual(coverage["incident-disclosure"].status,CoverageStatus.MISSING);self.assertEqual(outcome.status,"partial")

    def test_global_backend_budget_rejects_oversized_cross_domain_plan(self):
        snap=SnapshotManifestRef("m","c",NOW,("e","l","g"))
        too_small=PlanBudget(deadline_ms=5000,max_backend_calls=5,max_expansion_rounds=0,max_total_candidates=80,max_rerank_candidates=20,max_context_tokens=4000)
        with self.assertRaisesRegex(PlanValidationError,"backend-call budget"):
            incident_market_plan(SCOPE,snap,budget=too_small)

    def test_large_subquestion_cannot_crow_required_small_subquestion_from_packing(self):
        snap=SnapshotManifestRef("pack-m","pack-c",NOW,("lex",))
        q0=(passage("big1","r1","large corpus item one","lexical",1),passage("big2","r2","large corpus item two","lexical",2),passage("big3","r3","large corpus item three","lexical",3))
        q1=(passage("small","r4","small domain required evidence","lexical",1),)
        n0=PlanNode("big",PlanOperation.LEXICAL,"big","q-big",3,("quant",));n1=PlanNode("small",PlanOperation.LEXICAL,"small","q-small",1,("networking",))
        plan=QueryPlan("cross","cross",QueryIntent.CROSS_DOMAIN,SCOPE,snap,TemporalRequest(TemporalMode.CURRENT),PlanBudget(deadline_ms=1000,max_backend_calls=2,max_expansion_rounds=0,max_total_candidates=4,max_rerank_candidates=4,max_context_tokens=8),QueryFeatures(),(n0,n1),(),(),(),(Subquestion("q-big","big"),Subquestion("q-small","small")))
        execution=QueryExecution(plan.plan_id,(NodeExecution(n0,ChannelResult(ChannelStatus.OK,q0)),NodeExecution(n1,ChannelResult(ChannelStatus.OK,q1))),(),NOW,NOW)
        fusion=grouped_rrf(execution,top_k=4)
        labels=PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY)
        evidence=[EvidencePassage(row,labels,"fixture","origin-"+row.subquestion_id,snap.manifest_id) for row in fusion.passages]
        # Deliberately place all large-domain evidence before the small-domain evidence.
        evidence=sorted(evidence,key=lambda x:(x.subquestion_id=="q-small",x.passage.passage_uid))
        reranked=RerankOutcome(tuple(RerankedPassage(x,i,i,100-i,None) for i,x in enumerate(evidence,1)))
        text_by_revision={x.passage.revision_uid:x.passage.text for x in evidence}
        pack=asyncio.run(ContextPacker(WordTokenizer(),TextStore(text_by_revision)).pack(reranked,fusion,plan,ContextBudget(8,0,0,0)))
        self.assertEqual({p.evidence.subquestion_id for p in pack.passages},{"q-big","q-small"})
        self.assertTrue(all(p.citation_valid for p in pack.passages))

if __name__=="__main__":unittest.main()
