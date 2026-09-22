import asyncio,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path

from cti_rag.contracts import AccessLabel,CandidateBudget,CharacterSpanLocator,PassageHit,PolicyLabels,ProcessingClass,ProvenanceRef,ScoreDirection,ScoreMetadata,TemporalMode,TemporalRequest
from cti_rag.dense import DenseVectorRecord,DistanceMetric,EmbeddingFingerprint,EmbeddingInput,EmbeddingRuntime,InMemoryDenseIndex,MilvusDenseSearchPort,PoolingMode,QueryEmbeddingRuntime,SQLiteEmbeddingCache,VectorNormalization,measure_ann_recall
from cti_rag.policy.local import PublicOnlyLocalPolicy
from cti_rag.ports import AuthenticatedPrincipal,ClientScopeRequest,ProcessingDestination,ProjectionBuildRequest,SearchKind,SearchRequest
from cti_rag.retrieval import merge_passage_hits
from cti_rag.snapshots import SnapshotCatalogStore,SnapshotPublisher
from cti_rag.testing import DeterministicEmbeddingModel

UTC=timezone.utc
NOW=datetime(2026,1,1,tzinfo=UTC)

def fingerprint(revision="r1",dimension=8):
    return EmbeddingFingerprint("local","fixture-embed",revision,"fixture-tokenizer","t1",dimension,PoolingMode.MEAN,VectorNormalization.L2,DistanceMetric.COSINE,"title-section","1")
def public_labels(): return PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY)
def scope_for(policy): return policy.authorize(AuthenticatedPrincipal("alice","public"),ClientScopeRequest(("cybersecurity",)))
def query_labels(scope): return PolicyLabels(scope.tenant_id,AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY)

class Phase6DenseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.policy=PublicOnlyLocalPolicy.build("alice",("cybersecurity",)); self.scope=scope_for(self.policy)
    def tearDown(self): self.tmp.cleanup()
    def runtime(self,model=None,**kwargs):
        model=model or DeterministicEmbeddingModel(8)
        return model,EmbeddingRuntime(self.policy,model,SQLiteEmbeddingCache(self.root/f"cache-{id(model)}.db"),**kwargs)

    def test_embedding_fingerprint_partitions_cache_and_prevents_stale_reuse(self):
        model,runtime=self.runtime(); item=EmbeddingInput("p","r","same text","title",public_labels())
        asyncio.run(runtime.embed((item,),self.scope,fingerprint("r1"),ProcessingDestination("local",False)))
        asyncio.run(runtime.embed((item,),self.scope,fingerprint("r1"),ProcessingDestination("local",False)))
        self.assertEqual(model.calls,1)
        asyncio.run(runtime.embed((item,),self.scope,fingerprint("r2"),ProcessingDestination("local",False)))
        self.assertEqual(model.calls,2); self.assertEqual(runtime.cache.count(),2)

    def test_unauthorized_remote_provider_is_denied_before_text_transfer(self):
        model,runtime=self.runtime(); item=EmbeddingInput("p","r","private-query-material","",public_labels())
        with self.assertRaises(PermissionError):
            asyncio.run(runtime.embed((item,),self.scope,fingerprint(),ProcessingDestination("remote-provider",True)))
        self.assertEqual(model.calls,0); self.assertEqual(model.transferred_texts,[])

    def test_batched_embedding_is_bounded_and_retries_transient_failure(self):
        model=DeterministicEmbeddingModel(8,failures_before_success=1); _,runtime=self.runtime(model,max_batch_size=2,max_concurrency=1,max_retries=1)
        items=tuple(EmbeddingInput(f"p{i}",f"r{i}",f"text {i}","",public_labels()) for i in range(3))
        vectors=asyncio.run(runtime.embed(items,self.scope,fingerprint(),ProcessingDestination("local",False)))
        self.assertEqual(len(vectors),3); self.assertEqual(model.batch_sizes,[2,2,1]); self.assertEqual(max(model.batch_sizes),2)

    def test_deterministic_prefix_is_model_input_but_original_quote_is_unchanged(self):
        model,runtime=self.runtime(); item=EmbeddingInput("p","r","ORIGINAL QUOTATION","Title: Example | Section: Intro",public_labels())
        asyncio.run(runtime.embed((item,),self.scope,fingerprint(),ProcessingDestination("local",False)))
        self.assertEqual(item.text,"ORIGINAL QUOTATION")
        self.assertEqual(model.transferred_texts[0],"Title: Example | Section: Intro\n\nORIGINAL QUOTATION")

    def _dense_fixture(self,query_fp=None):
        catalog=SnapshotCatalogStore.sqlite(self.root/"catalog.db"); model=DeterministicEmbeddingModel(8); cache=SQLiteEmbeddingCache(self.root/"qcache.db")
        runtime=EmbeddingRuntime(self.policy,model,cache,max_batch_size=4,max_concurrency=1,max_retries=0); fp=fingerprint(); qfp=query_fp or fp
        qembed=QueryEmbeddingRuntime(runtime,qfp,ProcessingDestination("local",False),query_labels); index=InMemoryDenseIndex(catalog,qembed)
        vec=model._vector("alpha")
        records=(
            DenseVectorRecord("p-public","rev-public","obj-public","cybersecurity","fixture","public",AccessLabel.PUBLIC,NOW,None,None,'{"kind":"character_span","start":0,"end":5}',"alpha public",vec,"rep-public",fp.fingerprint_id),
            DenseVectorRecord("p-private","rev-private","obj-private","cybersecurity","fixture","public",AccessLabel.PRIVATE,NOW,None,None,'{"kind":"character_span","start":0,"end":5}',"alpha private",vec,"rep-private",fp.fingerprint_id),
            DenseVectorRecord("p-future","rev-future","obj-future","cybersecurity","fixture","public",AccessLabel.PUBLIC,datetime(2099,1,1,tzinfo=UTC),None,None,'{"kind":"character_span","start":0,"end":5}',"alpha future",vec,"rep-future",fp.fingerprint_id),
        )
        req=ProjectionBuildRequest("dense-g1","dense",tuple(sorted(r.revision_uid for r in records)),(fp.fingerprint_id,),("dense",),0)
        gen=index.build(req,records,fp); pub=SnapshotPublisher(catalog); pub.stage_generation(gen); manifest=pub.publish((gen.generation_id,),("dense",),created_at=NOW)
        return catalog,index,manifest,fp

    def test_snapshot_selected_dense_search_filters_private_future_and_current_revocation(self):
        catalog,index,manifest,fp=self._dense_fixture(); request=SearchRequest("alpha",SearchKind.DENSE,self.scope,TemporalRequest(TemporalMode.CURRENT),CandidateBudget(10,dense=10),manifest.to_ref())
        result=asyncio.run(index.search(request)); self.assertEqual(result.status.value,"ok"); self.assertEqual(tuple(h.passage_uid for h in result.items),("p-public",))
        catalog.admit_revocation("p-public","withdrawn",(),("dense",)); result=asyncio.run(index.search(request)); self.assertEqual(result.status.value,"empty")

    def test_query_embedding_fingerprint_must_match_snapshot_dense_generation(self):
        catalog,index,manifest,fp=self._dense_fixture(query_fp=fingerprint("different")); request=SearchRequest("alpha",SearchKind.DENSE,self.scope,TemporalRequest(TemporalMode.CURRENT),CandidateBudget(10,dense=10),manifest.to_ref())
        result=asyncio.run(index.search(request)); self.assertEqual(result.status.value,"rejected"); self.assertIn("fingerprint",result.reason)

    def test_ann_recall_is_measured_against_identical_exhaustive_eligible_set(self):
        broad=measure_ann_recall("broad",("p1","p2","p4"),("p1","p2","p3"),3,5)
        selective=measure_ann_recall("selective",("p2","p3"),("p2","p3"),2,2)
        self.assertAlmostEqual(broad.recall,2/3); self.assertEqual(selective.recall,1.0); self.assertEqual(selective.eligible_count,2)

    def test_dense_and_lexical_merge_by_passage_uid_preserves_channel_ranks(self):
        prov=ProvenanceRef("rev",CharacterSpanLocator(0,4))
        lexical=PassageHit("l","p","rev",prov,"text",(ScoreMetadata("lexical",0.2,ScoreDirection.LOWER_IS_BETTER,2,"fts"),))
        dense=PassageHit("d","p","rev",prov,"text",(ScoreMetadata("dense",0.8,ScoreDirection.HIGHER_IS_BETTER,1,"dense"),))
        merged=merge_passage_hits(((lexical,),(dense,)))
        self.assertEqual(len(merged),1); self.assertEqual({s.channel:s.raw_rank for s in merged[0].scores},{"lexical":2,"dense":1})

    def test_milvus_compatible_collection_identity_separates_embedding_spaces(self):
        class Client: pass
        class Q: pass
        q=Q(); q.fingerprint=fingerprint(); port=MilvusDenseSearchPort(Client(),object(),q,fingerprint())
        name1=port.collection_name("generation-a"); self.assertEqual(name1,port.collection_name("generation-a"))
        q2=Q(); q2.fingerprint=fingerprint("r2"); port2=MilvusDenseSearchPort(Client(),object(),q2,fingerprint("r2"))
        self.assertNotEqual(name1,port2.collection_name("generation-a")); self.assertIn(fingerprint().short_id,name1)

if __name__=="__main__": unittest.main()
