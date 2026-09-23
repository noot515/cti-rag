import asyncio,json,sqlite3,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace

from cti_rag.application.advanced_retrieval import AdvancedRetrievalService
from cti_rag.context import (
    ContextBudget,ContextPacker,EvidenceHydrator,EvidencePassage,EvidenceResponseStatus,FusionResult,
    PassageMetadata,PassageReranker,compare_b4_to_b3,
)
from cti_rag.contracts import (
    AccessLabel,CharacterSpanLocator,ComponentFingerprint,PassageHit,PolicyLabels,ProcessingClass,ProvenanceRef,
    SnapshotManifestRef,TemporalMode,TemporalRequest,locator_from_dict,
)
from cti_rag.ingestion import IngestionPipeline,SYNTHETIC_MANIFEST,SyntheticCyberConnector,SyntheticCyberNormalizer
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
from cti_rag.planning import DeterministicQueryPlanner,FusedPassage,PlanBudget,QueryExecutor,scope_hash
from cti_rag.policy.local import LocalPolicyProvider,PrincipalPolicy,PublicOnlyLocalPolicy
from cti_rag.ports import (
    AuthenticatedPrincipal,BackendCapabilities,ChannelResult,ChannelStatus,ClientScopeRequest,ProcessingDestination,
    ProjectionBuildRequest,ScoreDirection,
)
from cti_rag.retrieval import PersistentExactIndex,SQLiteFTS5LexicalIndex,StructuredJsonProjector
from cti_rag.snapshots import SnapshotCatalogStore,SnapshotPublisher

UTC=timezone.utc
NOW=datetime(2026,1,4,tzinfo=UTC)

class CharTokenizer:
    name="char-fixture";revision="1"
    @property
    def fingerprint(self):return "char-fixture/1"
    def encode(self,text):return tuple(ord(c) for c in text)
    def decode(self,tokens):return "".join(chr(v) for v in tokens)

class SpyReranker:
    def __init__(self,fail=False):
        self.capabilities=BackendCapabilities(model_fingerprint="spy-reranker/1");self.requests=[];self.fail=fail
    async def invoke(self,request):
        self.requests.append(request)
        if self.fail:raise RuntimeError("synthetic rerank failure")
        return {"scores":tuple(float(len(request.inputs)-i) for i,_ in enumerate(request.inputs))}

class DictEvidenceStore:
    def __init__(self,passages):self.passages=dict(passages)
    def get_passage(self,uid):return self.passages.get(uid)
    def resolve(self,provenance):
        for value in self.passages.values():
            if value.provenance==provenance:return value.text
        return None
    def get_revision(self,uid):return None
    def get_artifact(self,uid):return None
    def dependents(self,uid):return ()

class DictMetadataProvider:
    def __init__(self,values):self.values=dict(values)
    def get(self,uid):return self.values.get(uid)

class FakeManifest:
    manifest_id="manifest-fixture"
    corpus_digest="corpus"
    created_at=NOW
    projection_generation_ids=()
    def to_ref(self):return SnapshotManifestRef(self.manifest_id,self.corpus_digest,self.created_at,self.projection_generation_ids)
class FakeCatalog:
    def pin_current(self,scope):return SimpleNamespace(manifest=FakeManifest(),lease_id="lease")
    def release_lease(self,lease):pass

class Phase8EvidenceApiTests(unittest.TestCase):
    def test_spy_reranker_never_sees_denied_candidates_or_parent_expansion(self):
        policy=PublicOnlyLocalPolicy.build("alice",("cybersecurity",))
        scope=policy.authorize(AuthenticatedPrincipal("alice","public"),ClientScopeRequest(("cybersecurity",)))
        snap=SnapshotManifestRef("m","c",NOW,())
        pub_hit=PassageHit("h1","p1","r1",ProvenanceRef("r1",CharacterSpanLocator(0,11)),"public text")
        priv_hit=PassageHit("h2","p2","r2",ProvenanceRef("r2",CharacterSpanLocator(0,12)),"private text")
        store=DictEvidenceStore({
            "p1":SimpleNamespace(revision_uid="r1",provenance=pub_hit.provenance,text=pub_hit.text),
            "p2":SimpleNamespace(revision_uid="r2",provenance=priv_hit.provenance,text=priv_hit.text),
        })
        metadata=DictMetadataProvider({
            "p1":PassageMetadata(PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY),"src","origin-a","m"),
            "p2":PassageMetadata(PolicyLabels("public",AccessLabel.PRIVATE,ProcessingClass.LOCAL_ONLY),"src","origin-b","m"),
        })
        fused=(FusedPassage(pub_hit,1.0,(("lexical",1),),"q0"),FusedPassage(priv_hit,0.9,(("dense",1),),"q0"))
        hydrated,denied,invalid=EvidenceHydrator(store,metadata).hydrate(fused,scope,snap)
        self.assertEqual(tuple(v.passage.passage_uid for v in hydrated),("p1",));self.assertEqual((denied,invalid),(1,0))
        spy=SpyReranker();reranker=PassageReranker(policy,spy,ProcessingDestination("local",False))
        outcome=asyncio.run(reranker.rerank("query",hydrated,scope))
        self.assertEqual(len(spy.requests),1);self.assertEqual([x["text"] for x in spy.requests[0].inputs],["public text"])
        private_parent_hit=PassageHit("hp","pp","rp",ProvenanceRef("rp",CharacterSpanLocator(0,14)),"PRIVATE PARENT")
        private_parent=EvidencePassage(FusedPassage(private_parent_hit,0.1,(("parent",1),),"q0"),PolicyLabels("public",AccessLabel.PRIVATE,ProcessingClass.LOCAL_ONLY),"src","origin-parent","m")
        class ParentExpander:
            async def expand(self,evidence,scope,snapshot):return private_parent
        planner=DeterministicQueryPlanner()
        plan=planner.compile("query",scope,snap,TemporalRequest(TemporalMode.CURRENT),set())
        fusion=FusionResult((fused[0],),(),(),(),(),"cfg")
        packer=ContextPacker(CharTokenizer(),store,ParentExpander())
        packed=asyncio.run(packer.pack(outcome,fusion,plan,ContextBudget(128,8,8)))
        self.assertEqual(tuple(p.evidence.passage.passage_uid for p in packed.passages),("p1",))
        self.assertNotIn("PRIVATE PARENT",str(spy.requests[0].inputs))

    def test_reranker_failure_degrades_to_fused_order(self):
        policy=PublicOnlyLocalPolicy.build("alice",("cybersecurity",));scope=policy.authorize(AuthenticatedPrincipal("alice","public"),ClientScopeRequest(("cybersecurity",)))
        snap="m";items=[]
        for i,text in enumerate(("first","second"),1):
            hit=PassageHit(f"h{i}",f"p{i}",f"r{i}",ProvenanceRef(f"r{i}",CharacterSpanLocator(0,len(text))),text)
            items.append(EvidencePassage(FusedPassage(hit,1.0/i,(("lexical",i),),"q0"),PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY),"s",f"o{i}",snap))
        outcome=asyncio.run(PassageReranker(policy,SpyReranker(fail=True),ProcessingDestination("local",False)).rerank("q",items,scope))
        self.assertTrue(outcome.degraded);self.assertEqual(tuple(v.evidence.passage.passage_uid for v in outcome.passages),("p1","p2"))

    def test_token_budget_truncates_and_revalidates_citation_span(self):
        policy=PublicOnlyLocalPolicy.build("alice",("cybersecurity",));scope=policy.authorize(AuthenticatedPrincipal("alice","public"),ClientScopeRequest(("cybersecurity",)))
        text="abcdefghijklmnopqrstuvwxyz";hit=PassageHit("h","p","r",ProvenanceRef("r",CharacterSpanLocator(0,len(text))),text)
        store=DictEvidenceStore({"p":SimpleNamespace(revision_uid="r",provenance=hit.provenance,text=text)})
        ev=EvidencePassage(FusedPassage(hit,1.0,(("lexical",1),),"q0"),PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY),"s","origin","m")
        outcome=SimpleNamespace(passages=(SimpleNamespace(evidence=ev,score=1.0),),degraded=False,reasons=(),model_fingerprint=None)
        snap=SnapshotManifestRef("m","c",NOW,());plan=DeterministicQueryPlanner(server_budget=PlanBudget(max_context_tokens=20)).compile("q",scope,snap,TemporalRequest(TemporalMode.CURRENT),set())
        pack=asyncio.run(ContextPacker(CharTokenizer(),store,min_partial_tokens=4).pack(outcome,FusionResult((ev.fused,),(),(),(),(),"cfg"),plan,ContextBudget(20,2,2)))
        self.assertEqual(pack.used_tokens,16);self.assertTrue(pack.passages[0].truncated);self.assertTrue(pack.passages[0].citation_valid);self.assertEqual(pack.passages[0].display_text,text[:16])

    def _empty_service(self,result,policy=None):
        policy=policy or PublicOnlyLocalPolicy.build("alice",("cybersecurity",))
        from cti_rag.testing import CountingSearchPort
        ports={"lexical":CountingSearchPort(BackendCapabilities(score_direction=ScoreDirection.HIGHER_IS_BETTER),result),"dense":CountingSearchPort(BackendCapabilities(score_direction=ScoreDirection.HIGHER_IS_BETTER),result)}
        executor=QueryExecutor(ports)
        return AdvancedRetrievalService(policy,FakeCatalog(),DeterministicQueryPlanner(),executor,EvidenceHydrator(None,None),None,ContextPacker(CharTokenizer(),None),ContextBudget(128,8,8))

    def test_missing_evidence_is_distinct_from_backend_failure_and_trace_omits_raw_query(self):
        principal=AuthenticatedPrincipal("alice","public");client=ClientScopeRequest(("cybersecurity",));temporal=TemporalRequest(TemporalMode.CURRENT)
        empty=asyncio.run(self._empty_service(ChannelResult(ChannelStatus.EMPTY,reason="fixture empty")).retrieve(query="sensitive raw query",principal=principal,client_scope=client,temporal=temporal))
        failed=asyncio.run(self._empty_service(ChannelResult(ChannelStatus.UNAVAILABLE,reason="backend secret details")).retrieve(query="sensitive raw query",principal=principal,client_scope=client,temporal=temporal))
        self.assertEqual(empty.status,EvidenceResponseStatus.INSUFFICIENT_EVIDENCE);self.assertEqual(failed.status,EvidenceResponseStatus.FAILED)
        rule=PrincipalPolicy("alice","public",("cybersecurity",),debug_traces_allowed=True)
        debug_policy=LocalPolicyProvider((rule,))
        traced=asyncio.run(self._empty_service(ChannelResult(ChannelStatus.EMPTY,reason="empty"),debug_policy).retrieve(query="sensitive raw query",principal=principal,client_scope=client,temporal=temporal,debug=True))
        self.assertIsNotNone(traced.trace);self.assertFalse(hasattr(traced.trace,"query"));self.assertNotEqual(traced.trace.query_digest,"sensitive raw query")

    def test_b4_fixture_is_honest_about_fake_model_status(self):
        row=compare_b4_to_b3(b3_ranking=("x","p"),b4_ranking=("p","x"),relevant=("p",),k=2,scope_hash="scope",snapshot_id="m",real_model_status="not_run")
        self.assertGreater(row.b4_reciprocal_rank,row.b3_reciprocal_rank);self.assertFalse(row.semantic_quality_claim);self.assertEqual(row.real_model_status,"not_run")

    def test_source_ingestion_to_published_indexes_to_advanced_evidence_response(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);obj=FileObjectStore(root/"objects");meta=CanonicalMetadataStore.sqlite(root/"meta.db",object_exists=obj.exists)
            asyncio.run(IngestionPipeline(SYNTHETIC_MANIFEST,SyntheticCyberConnector(page_size=2),SyntheticCyberNormalizer(),obj,meta).ingest_page(None))
            conn=sqlite3.connect(root/"meta.db")
            try:rows=conn.execute("SELECT a.artifact_uid,a.revision_uid,a.object_digest,r.object_uid FROM artifacts a JOIN revisions r ON a.revision_uid=r.revision_uid ORDER BY a.revision_uid").fetchall()
            finally:conn.close()
            refs={ref.digest:ref for ref in obj.iter_refs()};projector=StructuredJsonProjector();records=[];docs=[];revisions=[]
            for artifact_uid,revision_uid,digest,object_uid in rows:
                normalized=obj.get(refs[digest]);data=json.loads(normalized.decode());available=datetime.fromisoformat(data["published_at"].replace("Z","+00:00"))
                exact,passages=projector.project(normalized_bytes=normalized,artifact_uid=artifact_uid,revision_uid=revision_uid,object_uid=object_uid,namespace="cve",object_type="cve",canonical_id=data["id"],domain="cybersecurity",source_id="synthetic-cyber",tenant_id="public",access_label=AccessLabel.PUBLIC,available_at=available,text_pointers=("/summary",),context_prefix=data["id"])
                records.append(exact);docs.extend(passages);revisions.append(revision_uid)
            revisions=tuple(sorted(revisions));catalog=SnapshotCatalogStore.sqlite(root/"catalog.db");exact_index=PersistentExactIndex.sqlite(root/"exact.db",catalog);lexical=SQLiteFTS5LexicalIndex(root/"lex.db",catalog)
            egen=exact_index.build(ProjectionBuildRequest("exact-e2e","exact",revisions,("canonical/1",),("exact",)),records);lgen=lexical.build(ProjectionBuildRequest("lex-e2e","lexical",revisions,("unicode61/1",),("lexical",)),docs)
            pub=SnapshotPublisher(catalog);pub.stage_generation(egen);pub.stage_generation(lgen);manifest=pub.publish(("exact-e2e","lex-e2e"),("exact","lexical"),created_at=NOW)
            passages={};metadata={}
            for doc in docs:
                provenance=ProvenanceRef(doc.revision_uid,locator_from_dict(json.loads(doc.locator_json)));passages[doc.passage_uid]=SimpleNamespace(revision_uid=doc.revision_uid,provenance=provenance,text=doc.original_text)
                metadata[doc.passage_uid]=PassageMetadata(PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY),"synthetic-cyber",doc.canonical_id,manifest.manifest_id,doc.available_at)
            store=DictEvidenceStore(passages);policy=PublicOnlyLocalPolicy.build("alice",("cybersecurity",));spy=SpyReranker()
            service=AdvancedRetrievalService(policy,catalog,DeterministicQueryPlanner(),QueryExecutor({"lexical":lexical},exact_index=exact_index),EvidenceHydrator(store,DictMetadataProvider(metadata)),PassageReranker(policy,spy,ProcessingDestination("local",False)),ContextPacker(CharTokenizer(),store),ContextBudget(256,16,16))
            principal=AuthenticatedPrincipal("alice","public");client=ClientScopeRequest(("cybersecurity",))
            evidence=asyncio.run(service.retrieve(query="synthetic buffer",principal=principal,client_scope=client,temporal=TemporalRequest(TemporalMode.CURRENT),top_k=5))
            self.assertIn(evidence.status,(EvidenceResponseStatus.COMPLETE,EvidenceResponseStatus.PARTIAL));self.assertTrue(evidence.passages);self.assertTrue(all(p.citation_valid for p in evidence.passages))
            exact=asyncio.run(service.retrieve(query="CVE-2026-0001",principal=principal,client_scope=client,temporal=TemporalRequest(TemporalMode.CURRENT),top_k=5))
            self.assertTrue(exact.exact);self.assertEqual(exact.exact[0].status.value,"found")

if __name__=="__main__":unittest.main()
