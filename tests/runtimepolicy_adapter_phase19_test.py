from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

import respectful_runtime as rr
from respectful_runtime.broker_client import receive_frame,send_frame

from cti_rag.contracts import AccessLabel,PolicyLabels,ProcessingClass
from cti_rag.infrastructure.runtimepolicy import RuntimePolicyDenied,RuntimePolicyProvider,RuntimePolicyUnavailable
from cti_rag.policy.local import PublicOnlyLocalPolicy
from cti_rag.ports import AuthenticatedPrincipal,ClientScopeRequest,NetworkDestination,ProcessingDestination

FIXTURES=Path(__file__).resolve().parent/"fixtures"/"runtimepolicy"

class ContractServer:
    def __init__(self,compatibility=None):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"broker.sock"
        self.compatibility_value=compatibility or json.loads((FIXTURES/"compatibility-valid.json").read_text())
        self.revision="rev-1";self.registered={};self.records={};self.assess_count=0
        self.deny_target=None;self.deny_operation=None;self.expired=False;self.malformed_assessment=False
        self._stop=False;self.ready=threading.Event()
        self.thread=threading.Thread(target=self._run,daemon=True)
        self.thread.start();self.assert_ready()

    def assert_ready(self):
        if not self.ready.wait(2):raise RuntimeError("fixture broker did not start")

    def close(self):
        self._stop=True
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:s.connect(str(self.path))
        except Exception:pass
        self.thread.join(2);self.tmp.cleanup()

    def _assessment(self,action):
        now=int(time.time());denied=(self.deny_target==action.target or self.deny_operation==action.operation)
        facts=rr.Facts(
            authorized=not denied,protected_preserved=True,creates_value=False,causal_claim=False,
            value_identified=False,endorsement_identified=False,trust_claim=False,trust_verified=False,
            manipulation_claim=False,manipulation_resolved=False,query_available=False,endorsement="unknown",
            uncertainty_ppm=0,wrong_cost=0,query_cost=0,
        )
        evidence={"protected_options":rr.Evidence("reachability_check","fixture:reachability",False)}
        if not denied:evidence["authorization"]=rr.Evidence("user_instruction","fixture:review",False)
        issued=now-20;expires=now-1 if self.expired else now+120
        return rr.Assessment(rr.VERSION,f"assess-{self.assess_count}",action,"fixture-authority",self.revision,issued,expires,facts,evidence)

    def _handle(self,request):
        if type(request) is not dict or set(request)!={"version","method","params"}:return {"ok":False,"result":"invalid_request"}
        method=request["method"];params=request["params"]
        if method=="compatibility":return {"ok":True,"result":self.compatibility_value}
        if method=="revision":return {"ok":True,"result":self.revision}
        if method=="register":
            action=rr.Action.from_dict(params["action"]);self.registered[action.fingerprint]={"action":action,"payload":params["payload"],"host":params["host"],"details":params["details"]}
            return {"ok":True,"result":None}
        if method=="assess":
            self.assess_count+=1;action=rr.Action.from_dict(params["action"]);assessment=self._assessment(action)
            value=asdict(assessment)
            if self.malformed_assessment:value["unexpected"]="field"
            return {"ok":True,"result":value}
        if method=="audit":
            record=params["record"];self.records[record["action_fingerprint"]]=record;return {"ok":True,"result":None}
        if method=="check":
            action=rr.Action.from_dict(params["action"]);record=params["record"]
            if action.fingerprint not in self.records:return {"ok":False,"result":"unrecognized_or_replayed_admission"}
            assessment_revision=self.registered[action.fingerprint].get("revision",None)
            if self.revision!="rev-1":return {"ok":False,"result":"state_revision_mismatch"}
            if record.get("decision")!="act":return {"ok":False,"result":"decision_not_act"}
            return {"ok":True,"result":None}
        if method=="release":return {"ok":True,"result":None}
        return {"ok":False,"result":"broker_method_or_fields_denied"}

    def _run(self):
        if self.path.exists():self.path.unlink()
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
            server.bind(str(self.path));server.listen(8);self.ready.set()
            while not self._stop:
                try:conn,_=server.accept()
                except OSError:break
                with conn:
                    if self._stop:break
                    try:send_frame(conn,self._handle(receive_frame(conn)))
                    except Exception as exc:
                        try:send_frame(conn,{"ok":False,"result":type(exc).__name__})
                        except Exception:pass

class RuntimePolicyPhase19Test(unittest.TestCase):
    def setUp(self):
        self.server=ContractServer()
        self.client=rr.AuthorityClient(self.server.path,timeout=1,protocol_version=3)
        self.provider=RuntimePolicyProvider(
            self.client,rr,allowed_domains=("cybersecurity","privacy"),allowed_sources=None,
            allowed_access_labels=(AccessLabel.PUBLIC,AccessLabel.PRIVATE),
            allowed_processing_classes=(ProcessingClass.LOCAL_ONLY,ProcessingClass.LOCAL_OR_APPROVED_REMOTE),
            private_state_allowed=True,
        )
        self.principal=AuthenticatedPrincipal("alice","tenant-a","mfa")

    def tearDown(self):self.server.close()

    def request(self):
        return ClientScopeRequest(("privacy",),("source-a",),(AccessLabel.PRIVATE,),(ProcessingClass.LOCAL_ONLY,),"private_exposure_review")

    def test_exact_request_fields_are_bound_and_scope_does_not_expand(self):
        scope=self.provider.authorize(self.principal,self.request())
        self.assertEqual(scope.domains,("privacy",));self.assertEqual(scope.source_ids,("source-a",));self.assertEqual(scope.policy_epoch,"rev-1")
        self.assertEqual(scope.policy_provider,"runtimepolicy");self.assertEqual(scope.purpose,"private_exposure_review")
        admission=self.server.registered[scope.admission_action_fingerprint]
        payload=admission["payload"]
        self.assertEqual(payload["principal"],{"principal_id":"alice","tenant_id":"tenant-a","authn_context":"mfa"})
        self.assertEqual(payload["requested_scope"]["access_labels"],["private"])
        self.assertEqual(payload["requested_scope"]["processing_classes"],["local_only"])
        self.assertEqual(payload["purpose"],"private_exposure_review")
        self.assertEqual(admission["host"],"research")

    def test_response_revalidation_reuses_admission_and_detects_revision_change(self):
        scope=self.provider.authorize(self.principal,self.request());self.assertEqual(self.server.assess_count,1)
        self.assertIs(scope,self.provider.revalidate_for_response(scope,self.principal,self.request()))
        self.assertEqual(self.server.assess_count,1)
        self.server.revision="rev-2"
        with self.assertRaises(RuntimePolicyDenied):self.provider.revalidate_for_response(scope,self.principal,self.request())

    def test_expired_malformed_and_rejected_assessments_fail_closed(self):
        self.server.expired=True
        with self.assertRaises(RuntimePolicyUnavailable):self.provider.authorize(self.principal,self.request())
        self.server.expired=False;self.server.malformed_assessment=True
        with self.assertRaises(RuntimePolicyUnavailable):self.provider.authorize(self.principal,self.request())
        self.server.malformed_assessment=False;self.server.deny_operation="cti_rag.policy.scope"
        with self.assertRaises(RuntimePolicyDenied):self.provider.authorize(self.principal,self.request())

    def test_wrong_model_endpoint_and_local_only_remote_are_denied(self):
        scope=self.provider.authorize(self.principal,self.request())
        labels=PolicyLabels("tenant-a",AccessLabel.PRIVATE,ProcessingClass.LOCAL_ONLY)
        with self.assertRaises(RuntimePolicyDenied):
            self.provider.authorize_model(scope,labels,"generation",ProcessingDestination("remote-model",True))
        remote_labels=PolicyLabels("tenant-a",AccessLabel.PRIVATE,ProcessingClass.LOCAL_OR_APPROVED_REMOTE)
        scope2=self.provider.authorize(self.principal,ClientScopeRequest(("privacy",),(),(AccessLabel.PRIVATE,),(ProcessingClass.LOCAL_OR_APPROVED_REMOTE,),"answer"))
        self.server.deny_target="model:remote-model"
        with self.assertRaises(RuntimePolicyDenied):
            self.provider.authorize_model(scope2,remote_labels,"generation",ProcessingDestination("remote-model",True))

    def test_network_destination_is_exact_and_policy_checked(self):
        scope=self.provider.authorize(self.principal,ClientScopeRequest(("cybersecurity",),(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_OR_APPROVED_REMOTE,),"web_search"))
        labels=PolicyLabels("tenant-a",AccessLabel.PUBLIC,ProcessingClass.LOCAL_OR_APPROVED_REMOTE)
        self.provider.authorize_network(scope,labels,"web_search",NetworkDestination("searxng","https://search.example",True))
        latest=max(self.server.registered.values(),key=lambda item:item["action"].request_id)
        self.assertEqual(latest["payload"]["destination"]["endpoint"],"https://search.example")

    def test_invalid_compatibility_fixture_is_rejected(self):
        bad=json.loads((FIXTURES/"compatibility-invalid.json").read_text())
        self.server.compatibility_value=bad
        with self.assertRaises(RuntimePolicyUnavailable):
            RuntimePolicyProvider(self.client,rr,allowed_domains=("cybersecurity",))

    def test_external_unavailable_never_falls_back_to_private_local(self):
        self.server.close()
        with self.assertRaises(RuntimePolicyUnavailable):self.provider.authorize(self.principal,self.request())
        local=PublicOnlyLocalPolicy.build("public-user")
        with self.assertRaises(Exception):
            local.authorize(AuthenticatedPrincipal("public-user","public"),ClientScopeRequest(("privacy",),access_labels=(AccessLabel.PRIVATE,)))

    def test_local_public_mode_remains_explicit_and_separate(self):
        local=PublicOnlyLocalPolicy.build("public-user")
        scope=local.authorize(AuthenticatedPrincipal("public-user","public"),ClientScopeRequest(("cybersecurity",)))
        self.assertEqual(scope.policy_provider,"local");self.assertEqual(scope.access_labels,(AccessLabel.PUBLIC,))

if __name__=="__main__":unittest.main()
