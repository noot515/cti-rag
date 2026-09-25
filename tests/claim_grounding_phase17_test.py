from __future__ import annotations
import unittest
from datetime import datetime,timezone
from decimal import Decimal
from types import SimpleNamespace
from cti_rag.context import ContextBudget,ContextPacker,EvidencePassage,PackedPassage,RerankedPassage,RerankOutcome
from cti_rag.contracts import AccessLabel,CharacterSpanLocator,PassageHit,PolicyLabels,ProcessingClass,ProvenanceRef,ScoreMetadata,SnapshotManifestRef,TemporalMode,TemporalRequest
from cti_rag.grounding import BoundedFollowUpSearch,ClaimCitation,ClaimGrounder,ClaimStatus,FollowUpProposal,GeneratedClaim,GroundedAnswerService,JudgeEvaluationStatus,NumericFact,SemanticStatus
from cti_rag.planning import FusedPassage,PlanBudget
from cti_rag.ports import BackendCapabilities,ChannelResult,ChannelStatus,EffectiveScope,ProcessingDestination

class _Tokenizer:
    name="fixture";revision="1"
    def encode(self,text):return tuple(str(text).split())
    def decode(self,tokens):return " ".join(tokens)

def _scope():
    return EffectiveScope("p1","public",("cybersecurity",),(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_ONLY,),7,False,False)

def _packed(uid,text,*,origin="origin-a",unit=None,conflict_group=None,entity_key="entity:1",valid_time="2026-01-01",edition_key=None,revision=None,citation_valid=True):
    revision=revision or f"rev:{uid}";prov=ProvenanceRef(revision,CharacterSpanLocator(0,len(text)))
    hit=PassageHit(f"hit:{uid}",uid,revision,prov,text,(ScoreMetadata("lexical",1.0),));fused=FusedPassage(hit,1.0,(("lexical",1),),"q0")
    labels=PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY)
    evidence=EvidencePassage(fused,labels,"fixture-source",origin,"snap:1",None,"source_claim",unit,None,conflict_group,entity_key,valid_time,edition_key)
    return PackedPassage(evidence,text,len(text.split()),False,citation_valid)

class _SearchSpy:
    capabilities=BackendCapabilities(supported_filters=frozenset({"tenant","domain","access_label"}),snapshot_support=True)
    def __init__(self,result):self.result=result;self.requests=[]
    async def search(self,request):self.requests.append(request);return self.result

class _Policy:
    def __init__(self,scope):self.scope=scope
    def authorize(self,principal,client_scope):return self.scope
    def authorize_model(self,scope,labels,operation,destination):return None

class _Generator:
    capabilities=BackendCapabilities(model_fingerprint="generator-fixture/1")
    def __init__(self,payload):self.payload=payload
    async def invoke(self,request):return self.payload

class _FailJudge:
    fingerprint="judge-fixture/1"
    async def judge(self,claim,spans):raise RuntimeError("synthetic judge failure")

class ClaimGroundingPhase17Test(unittest.IsolatedAsyncioTestCase):
    async def test_exact_quote_identifier_date_and_numeric_checks(self):
        passage=_packed("p1","On 2026-01-01 ACME reported revenue 10 USD. Exact quote here.",unit="USD")
        grounder=ClaimGrounder()
        good=GeneratedClaim("c1","ACME reported 10 USD.",(ClaimCitation("p1"),),quoted_text="Exact quote here.",identifiers=("ACME",),dates=("2026-01-01",),numbers=(NumericFact(Decimal("10"),"USD"),),entity_key="entity:1",valid_time="2026-01-01")
        self.assertEqual(ClaimStatus.SUPPORTED,(await grounder.assess(good,(passage,))).status)
        fabricated=GeneratedClaim("c2","fabricated",(ClaimCitation("p1"),),quoted_text="not in source")
        self.assertEqual(ClaimStatus.INSUFFICIENT,(await grounder.assess(fabricated,(passage,))).status)
        altered=GeneratedClaim("c3","ACME reported 11 USD.",(ClaimCitation("p1"),),numbers=(NumericFact(Decimal("11"),"USD"),),entity_key="entity:1",valid_time="2026-01-01")
        self.assertEqual(ClaimStatus.CONTRADICTED,(await grounder.assess(altered,(passage,))).status)

    async def test_invalid_citation_is_not_support(self):
        passage=_packed("p1","CVE-2026-1234",citation_valid=False)
        claim=GeneratedClaim("c1","listed",(ClaimCitation("p1"),),identifiers=("CVE-2026-1234",))
        result=await ClaimGrounder().assess(claim,(passage,))
        self.assertEqual(ClaimStatus.INSUFFICIENT,result.status)
        self.assertTrue(any(c.kind=="citation" and c.status.value=="fail" for c in result.checks))

    async def test_unit_time_edition_revision_mismatch_not_direct_contradiction(self):
        eur=_packed("eur","ACME reported 9 EUR.",unit="EUR",valid_time="2026-01-01")
        old=_packed("old","ACME reported 9 USD.",unit="USD",valid_time="2025-01-01",edition_key="old")
        claim=GeneratedClaim("c","ACME reported 10 USD.",(ClaimCitation("eur"),ClaimCitation("old")),numbers=(NumericFact(Decimal("10"),"USD"),),entity_key="entity:1",valid_time="2026-01-01",edition_key="new",source_revision="rev:new")
        result=await ClaimGrounder().assess(claim,(eur,old))
        self.assertEqual(ClaimStatus.INSUFFICIENT,result.status);self.assertFalse(result.conflicting_spans)

    async def test_origin_group_deduplicates_confirmation(self):
        a=_packed("a","CVE-2026-1234",origin="wire");b=_packed("b","CVE-2026-1234",origin="wire")
        result=await ClaimGrounder().assess(GeneratedClaim("c","listed",(ClaimCitation("a"),ClaimCitation("b")),identifiers=("CVE-2026-1234",)),(a,b))
        self.assertEqual(("wire",),result.support_origin_groups)

    async def test_semantic_judge_failure_is_separate(self):
        p=_packed("p","semantic prose")
        result=await ClaimGrounder(_FailJudge()).assess(GeneratedClaim("c","claim",(ClaimCitation("p"),)),(p,))
        self.assertEqual(ClaimStatus.INSUFFICIENT,result.status);self.assertEqual(SemanticStatus.ERROR,result.semantic.status);self.assertEqual(JudgeEvaluationStatus.ERROR,result.semantic.evaluation_status)

    async def test_one_followup_preserves_scope_snapshot_and_cannot_recurse(self):
        spy=_SearchSpy(ChannelResult(ChannelStatus.EMPTY,reason="empty"))
        plan=SimpleNamespace(scope=_scope(),temporal=TemporalRequest(TemporalMode.CURRENT),snapshot=SnapshotManifestRef("snap:1","digest",datetime.now(timezone.utc),()),nodes=(),budget=PlanBudget(max_backend_calls=2))
        follow=BoundedFollowUpSearch(spy,remaining_calls=1,remaining_tokens=50)
        first=await follow.search(FollowUpProposal("competing account","missing",0,4,20),original_plan=plan)
        self.assertTrue(first.accepted);self.assertEqual(plan.scope,spy.requests[0].scope);self.assertEqual(plan.snapshot,spy.requests[0].snapshot)
        second=await follow.search(FollowUpProposal("again","nested",0,4,20),original_plan=plan)
        self.assertFalse(second.attempted);self.assertEqual(1,len(spy.requests))
        recursive=BoundedFollowUpSearch(spy)
        denied=await recursive.search(FollowUpProposal("nested","bad",depth=1),original_plan=plan)
        self.assertFalse(denied.accepted);self.assertEqual(1,len(spy.requests))

    async def test_generation_drops_unsupported_but_keeps_answerable_claim(self):
        p=_packed("p1","ACME reported revenue 10 USD.",unit="USD")
        response=SimpleNamespace(status=SimpleNamespace(value="complete"),passages=(p,))
        generator=_Generator({"claims":[
            {"claim_id":"good","text":"ACME reported 10 USD.","citations":[{"passage_uid":"p1"}],"numbers":[{"value":"10","unit":"USD"}],"entity_key":"entity:1","valid_time":"2026-01-01"},
            {"claim_id":"bad","text":"ACME reported 99 USD.","citations":[{"passage_uid":"p1"}],"numbers":[{"value":"99","unit":"USD"}],"entity_key":"entity:1","valid_time":"2026-01-01"}]})
        result=await GroundedAnswerService(policy=_Policy(_scope()),generator=generator,grounder=ClaimGrounder(),destination=ProcessingDestination("local",False)).generate(query="revenue?",principal=object(),client_scope=object(),evidence_response=response)
        self.assertEqual("ACME reported 10 USD.",result.answer);self.assertEqual(("bad",),tuple(c.claim_id for c in result.unresolved));self.assertEqual("generator-fixture/1",result.generation_fingerprint)

    async def test_packer_preserves_distinct_origins_for_conflict_group(self):
        a=_packed("a","conflicting alpha",origin="origin-a",conflict_group="issue");b=_packed("b","conflicting beta",origin="origin-b",conflict_group="issue");c=_packed("c","high relevance",origin="origin-c")
        reranked=RerankOutcome((RerankedPassage(c.evidence,1,1,1.0),RerankedPassage(a.evidence,2,2,.9),RerankedPassage(b.evidence,3,3,.8)))
        plan=SimpleNamespace(budget=PlanBudget(max_context_tokens=30),scope=_scope(),snapshot=SnapshotManifestRef("snap:1","digest",datetime.now(timezone.utc),()))
        fusion=SimpleNamespace(gaps=(),exact_obligations=(),structured_obligations=(),graph_paths=(),join_results=())
        packed=await ContextPacker(_Tokenizer(),min_partial_tokens=1).pack(reranked,fusion,plan,ContextBudget(30,0,0))
        selected={x.evidence.passage.passage_uid for x in packed.passages}
        self.assertTrue({"a","b"}.issubset(selected))

if __name__=="__main__":unittest.main()
