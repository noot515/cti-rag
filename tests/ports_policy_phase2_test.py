import ast,asyncio,unittest
from pathlib import Path
from cti_rag.application.guarded import authorized_model_call, authorized_search
from cti_rag.composition import build_public_only_runtime
from cti_rag.contracts import AccessLabel,CandidateBudget,PolicyLabels,ProcessingClass,TemporalMode,TemporalRequest
from cti_rag.domains import DomainSpec,IdentifierParser,RelationRule,builtin_registry
from cti_rag.policy.local import LocalPolicyProvider,PrincipalPolicy,PublicOnlyLocalPolicy
from cti_rag.ports import AuthenticatedPrincipal,BackendCapabilities,ChannelStatus,ClientScopeRequest,ModelOperation,PolicyDenied,ProcessingDestination,ScoreDirection,SearchKind
from cti_rag.testing import CountingModelPort,CountingSearchPort,FailingPolicy

class Phase2Tests(unittest.TestCase):
    def test_minimal_boundaries_do_not_import_optional_sdks(self):
        root=Path(__file__).resolve().parents[1]/"cti_rag"
        banned={"pymilvus","neo4j","opencti","sqlalchemy","fastapi","openai","dashscope","zhipuai"}
        for folder in ("contracts","ports","domains","policy","composition"):
            for path in (root/folder).rglob("*.py"):
                tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node,ast.Import):
                        for alias in node.names:self.assertNotIn(alias.name.split(".")[0],banned,path)
                    elif isinstance(node,ast.ImportFrom) and node.module:
                        self.assertNotIn(node.module.split(".")[0],banned,path)
        runtime=build_public_only_runtime(); self.assertIn("cybersecurity",runtime.domains.names())

    def test_sixth_fixture_domain_registers_without_orchestration_edit(self):
        reg=builtin_registry()
        spec=DomainSpec("fixture6",("fixture/1",),(IdentifierParser("fixture",r"F-[0-9]+",True),),(("lookup","exact"),),(RelationRule("related_to",("fixture",),("fixture",)),),({"id":"F-1"},))
        reg.register(spec)
        self.assertEqual(reg.get("fixture6").parse_identifier("f-12"),("fixture","F-12"))

    def test_forged_client_identity_fields_cannot_grant_access(self):
        policy=LocalPolicyProvider((PrincipalPolicy("alice","tenant-a",("cybersecurity",),access_labels=(AccessLabel.PUBLIC,)),))
        principal=AuthenticatedPrincipal("alice","tenant-a")
        requested=ClientScopeRequest.from_payload({"principal_id":"admin","tenant_id":"tenant-z","clearance":"private","domains":["cybersecurity"],"access_labels":["public"]})
        scope=policy.authorize(principal,requested)
        self.assertEqual(scope.principal_id,"alice"); self.assertEqual(scope.tenant_id,"tenant-a"); self.assertEqual(scope.access_labels,(AccessLabel.PUBLIC,))

    def test_denied_search_never_calls_backend(self):
        backend=CountingSearchPort(BackendCapabilities(supported_filters=frozenset({"tenant","domain","access_label"}),score_direction=ScoreDirection.HIGHER_IS_BETTER))
        result=asyncio.run(authorized_search(policy=PublicOnlyLocalPolicy.build("public-user"),principal=AuthenticatedPrincipal("intruder","public"),client_scope=ClientScopeRequest(("cybersecurity",)),backend=backend,query="x",kind=SearchKind.LEXICAL,temporal=TemporalRequest(TemporalMode.CURRENT),budget=CandidateBudget(5)))
        self.assertEqual(result.status,ChannelStatus.REJECTED); self.assertEqual(backend.calls,0)

    def test_unsupported_mandatory_filter_rejects_without_backend_call(self):
        backend=CountingSearchPort(BackendCapabilities(supported_filters=frozenset({"tenant","domain"})))
        result=asyncio.run(authorized_search(policy=PublicOnlyLocalPolicy.build("public-user"),principal=AuthenticatedPrincipal("public-user","public"),client_scope=ClientScopeRequest(("cybersecurity",)),backend=backend,query="x",kind=SearchKind.LEXICAL,temporal=TemporalRequest(TemporalMode.CURRENT),budget=CandidateBudget(5)))
        self.assertEqual(result.status,ChannelStatus.REJECTED); self.assertIn("filter:access_label",result.reason); self.assertEqual(backend.calls,0)

    def test_local_only_evidence_cannot_dispatch_remote(self):
        rule=PrincipalPolicy("alice","tenant-a",("cybersecurity",),access_labels=(AccessLabel.PUBLIC,),processing_classes=(ProcessingClass.LOCAL_ONLY,),allowed_model_destinations=((ModelOperation.RERANK.value,("remote-reranker","local")),))
        policy=LocalPolicyProvider((rule,)); scope=policy.authorize(AuthenticatedPrincipal("alice","tenant-a"),ClientScopeRequest(("cybersecurity",)))
        model=CountingModelPort(BackendCapabilities(model_fingerprint="fake/1")); labels=PolicyLabels("tenant-a",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY)
        with self.assertRaises(PolicyDenied):
            asyncio.run(authorized_model_call(policy=policy,scope=scope,model=model,operation=ModelOperation.RERANK,inputs=("text",),labels=labels,destination=ProcessingDestination("remote-reranker",True)))
        self.assertEqual(model.calls,0)

    def test_policy_failure_blocks_protected_access(self):
        backend=CountingSearchPort(BackendCapabilities(supported_filters=frozenset({"tenant","domain","access_label"})))
        result=asyncio.run(authorized_search(policy=FailingPolicy(),principal=AuthenticatedPrincipal("alice","tenant-a"),client_scope=ClientScopeRequest(("cybersecurity",),access_labels=(AccessLabel.PRIVATE,)),backend=backend,query="private",kind=SearchKind.EXACT,temporal=TemporalRequest(TemporalMode.CURRENT),budget=CandidateBudget(1)))
        self.assertEqual(result.status,ChannelStatus.REJECTED); self.assertEqual(backend.calls,0)

    def test_public_only_mode_rejects_private_scope(self):
        policy=PublicOnlyLocalPolicy.build("public-user")
        with self.assertRaises(PolicyDenied):
            policy.authorize(AuthenticatedPrincipal("public-user","public"),ClientScopeRequest(("privacy",),access_labels=(AccessLabel.PRIVATE,)))

if __name__=="__main__": unittest.main()
