from __future__ import annotations

from dataclasses import asdict,dataclass
import hashlib,json
from pathlib import Path
import socket,struct,tempfile,threading,time,unittest

from cti_rag.contracts import AccessLabel,PolicyLabels,ProcessingClass
from cti_rag.infrastructure.runtimepolicy import RuntimePolicyDenied,RuntimePolicyProvider,RuntimePolicyUnavailable
from cti_rag.policy.local import PublicOnlyLocalPolicy
from cti_rag.ports import AuthenticatedPrincipal,ClientScopeRequest,NetworkDestination,ProcessingDestination

FIXTURES=Path(__file__).resolve().parent/"fixtures"/"runtimepolicy"

def _canonical(value):return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def _send(sock,value):
    raw=_canonical(value).encode();sock.sendall(struct.pack("!I",len(raw))+raw)
def _recv(sock):
    header=b""
    while len(header)<4:
        chunk=sock.recv(4-len(header))
        if not chunk:raise EOFError()
        header+=chunk
    size=struct.unpack("!I",header)[0]
    if size>1_048_576:raise ValueError("fixture frame too large")
    body=b""
    while len(body)<size:
        chunk=sock.recv(size-len(body))
        if not chunk:raise EOFError()
        body+=chunk
    return json.loads(body)

@dataclass(frozen=True)
class Action:
    request_id:str;operation:str;target:str;payload_sha256:str
    @classmethod
    def for_payload(cls,request_id,operation,target,payload):
        return cls(request_id,operation,target,hashlib.sha256(_canonical(payload).encode()).hexdigest())
    @property
    def fingerprint(self):return hashlib.sha256(_canonical(asdict(self)).encode()).hexdigest()
    @classmethod
    def from_dict(cls,value):return cls(**value)

@dataclass(frozen=True)
class Assessment:
    schema_version:str;assessment_id:str;action:Action;issuer:str;state_revision:str;issued_at:int;expires_at:int;facts:dict;evidence:dict
    @classmethod
    def from_dict(cls,value):
        expected={"schema_version","assessment_id","action","issuer","state_revision","issued_at","expires_at","facts","evidence"}
        if type(value) is not dict or set(value)!=expected:raise ValueError("invalid assessment fixture schema")
        return cls(value["schema_version"],value["assessment_id"],Action.from_dict(value["action"]),value["issuer"],value["state_revision"],value["issued_at"],value["expires_at"],value["facts"],value["evidence"])

@dataclass(frozen=True)
class DecisionRecord:
    schema_version:str;action_fingerprint:str;decision:str;reasons:tuple;assessment_id:str|None=None
    def to_dict(self):return {"schema_version":self.schema_version,"action_fingerprint":self.action_fingerprint,"decision":self.decision,"reasons":list(self.reasons),"assessment_id":self.assessment_id}

class RuntimePolicy:
    def evaluate(self,action,assessment,now):
        if assessment.action!=action or now>=assessment.expires_at:raise ValueError("expired_or_unbound")
        authorized=assessment.facts.get("authorized") is True and assessment.facts.get("protected_preserved") is True
        return DecisionRecord("1.0.0",action.fingerprint,"act" if authorized else "reject",("conditions_satisfied",) if authorized else ("scope_not_authorized",),assessment.assessment_id)

class FixtureRuntime:
    VERSION="1.0.0";RUNTIME_VERSION="1.4.0";BROKER_PROTOCOL_VERSION=3
    Action=Action;Assessment=Assessment;RuntimePolicy=RuntimePolicy

class FixtureAuthorityClient:
    clock=staticmethod(time.time)
    def __init__(self,path,timeout=1):self.path=str(path);self.timeout=timeout
    def _call(self,method,params=None):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
            s.settimeout(self.timeout);s.connect(self.path);_send(s,{"version":3,"method":method,"params":params or {}});reply=_recv(s)
        if type(reply) is not dict or set(reply)!={"ok","result"} or type(reply["ok"]) is not bool:raise ValueError("invalid broker response")
        if not reply["ok"]:raise RuntimeError(str(reply["result"]))
        return reply["result"]
    def compatibility(self):return self._call("compatibility")
    def current_revision(self):return self._call("revision")
    def register_request(self,action,*,payload,host,details=None,mutates_state=False):return self._call("register",{"action":asdict(action),"payload":payload,"host":host,"details":details,"mutates_state":mutates_state})
    def __call__(self,action):return Assessment.from_dict(self._call("assess",{"action":asdict(action)}))
    def audit(self,record):return self._call("audit",{"record":record.to_dict()})
    def check(self,action,record):return self._call("check",{"action":asdict(action),"record":record.to_dict()})

class ContractServer:
    def __init__(self,compatibility=None):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"broker.sock"
        self.compatibility_value=compatibility or json.loads((FIXTURES/"compatibility-valid.json").read_text())
        self.revision="rev-1";self.registered={};self.records={};self.assess_count=0
        self.deny_target=None;self.deny_operation=None;self.expired=False;self.malformed_assessment=False
        self._stop=False;self.ready=threading.Event();self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()
        if not self.ready.wait(2):raise RuntimeError("fixture broker did not start")
    def close(self):
        if self._stop:return
        self._stop=True
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:s.connect(str(self.path))
        except Exception:pass
        self.thread.join(2);self.tmp.cleanup()
    def _assessment(self,action):
        now=int(time.time());denied=self.deny_target==action.target or self.deny_operation==action.operation
        return {
            "schema_version":"1.0.0","assessment_id":f"assess-{self.assess_count}","action":asdict(action),
            "issuer":"recorded-fixture-authority","state_revision":self.revision,"issued_at":now-20,
            "expires_at":now-1 if self.expired else now+120,
            "facts":{"authorized":not denied,"protected_preserved":True},
            "evidence":{"authorization":{"kind":"user_instruction","source":"recorded:review","independent":False},"protected_options":{"kind":"reachability_check","source":"recorded:reachability","independent":False}},
        }
    def _handle(self,request):
        if type(request) is not dict or set(request)!={"version","method","params"} or request["version"]!=3:return {"ok":False,"result":"invalid_request"}
        method=request["method"];params=request["params"]
        if method=="compatibility":return {"ok":True,"result":self.compatibility_value}
        if method=="revision":return {"ok":True,"result":self.revision}
        if method=="register":
            action=Action.from_dict(params["action"]);self.registered[action.fingerprint]={"action":action,"payload":params["payload"],"host":params["host"],"details":params["details"]}
            return {"ok":True,"result":None}
        if method=="assess":
            self.assess_count+=1;action=Action.from_dict(params["action"]);value=self._assessment(action)
            if self.malformed_assessment:value["unexpected"]="field"
            return {"ok":True,"result":value}
        if method=="audit":
            record=params["record"];self.records[record["action_fingerprint"]]=record;return {"ok":True,"result":None}
        if method=="check":
            action=Action.from_dict(params["action"]);record=params["record"]
            if action.fingerprint not in self.records:return {"ok":False,"result":"unrecognized_or_replayed_admission"}
            if self.revision!="rev-1":return {"ok":False,"result":"state_revision_mismatch"}
            if record.get("decision")!="act":return {"ok":False,"result":"decision_not_act"}
            return {"ok":True,"result":None}
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
                    try:_send(conn,self._handle(_recv(conn)))
                    except Exception as exc:
                        try:_send(conn,{"ok":False,"result":type(exc).__name__})
                        except Exception:pass

class RuntimePolicyPhase19Test(unittest.TestCase):
    def setUp(self):
        self.server=ContractServer();self.client=FixtureAuthorityClient(self.server.path)
        self.provider=RuntimePolicyProvider(self.client,FixtureRuntime,allowed_domains=("cybersecurity","privacy"),allowed_sources=None,allowed_access_labels=(AccessLabel.PUBLIC,AccessLabel.PRIVATE),allowed_processing_classes=(ProcessingClass.LOCAL_ONLY,ProcessingClass.LOCAL_OR_APPROVED_REMOTE),private_state_allowed=True)
        self.principal=AuthenticatedPrincipal("alice","tenant-a","mfa")
    def tearDown(self):self.server.close()
    def request(self):return ClientScopeRequest(("privacy",),("source-a",),(AccessLabel.PRIVATE,),(ProcessingClass.LOCAL_ONLY,),"private_exposure_review")

    def test_exact_request_fields_are_bound_and_scope_does_not_expand(self):
        scope=self.provider.authorize(self.principal,self.request())
        self.assertEqual(scope.domains,("privacy",));self.assertEqual(scope.source_ids,("source-a",));self.assertEqual(scope.policy_epoch,"rev-1")
        self.assertEqual(scope.policy_provider,"runtimepolicy");self.assertEqual(scope.purpose,"private_exposure_review")
        payload=self.server.registered[scope.admission_action_fingerprint]["payload"]
        self.assertEqual(payload["principal"],{"principal_id":"alice","tenant_id":"tenant-a","authn_context":"mfa"})
        self.assertEqual(payload["requested_scope"]["access_labels"],["private"]);self.assertEqual(payload["requested_scope"]["processing_classes"],["local_only"])
        self.assertEqual(payload["purpose"],"private_exposure_review")

    def test_response_revalidation_reuses_admission_and_detects_revision_change(self):
        scope=self.provider.authorize(self.principal,self.request());self.assertEqual(self.server.assess_count,1)
        self.assertIs(scope,self.provider.revalidate_for_response(scope,self.principal,self.request()));self.assertEqual(self.server.assess_count,1)
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
        scope=self.provider.authorize(self.principal,self.request());labels=PolicyLabels("tenant-a",AccessLabel.PRIVATE,ProcessingClass.LOCAL_ONLY)
        with self.assertRaises(RuntimePolicyDenied):self.provider.authorize_model(scope,labels,"generation",ProcessingDestination("remote-model",True))
        scope2=self.provider.authorize(self.principal,ClientScopeRequest(("privacy",),(),(AccessLabel.PRIVATE,),(ProcessingClass.LOCAL_OR_APPROVED_REMOTE,),"answer"))
        self.server.deny_target="model:remote-model";remote_labels=PolicyLabels("tenant-a",AccessLabel.PRIVATE,ProcessingClass.LOCAL_OR_APPROVED_REMOTE)
        with self.assertRaises(RuntimePolicyDenied):self.provider.authorize_model(scope2,remote_labels,"generation",ProcessingDestination("remote-model",True))

    def test_network_destination_is_exact_and_policy_checked(self):
        scope=self.provider.authorize(self.principal,ClientScopeRequest(("cybersecurity",),(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_OR_APPROVED_REMOTE,),"web_search"))
        self.provider.authorize_network(scope,PolicyLabels("tenant-a",AccessLabel.PUBLIC,ProcessingClass.LOCAL_OR_APPROVED_REMOTE),"web_search",NetworkDestination("searxng","https://search.example",True))
        matching=[v for v in self.server.registered.values() if v["action"].target=="network:searxng"]
        self.assertEqual(1,len(matching));self.assertEqual("https://search.example",matching[0]["payload"]["destination"]["endpoint"])

    def test_invalid_compatibility_fixture_is_rejected(self):
        self.server.compatibility_value=json.loads((FIXTURES/"compatibility-invalid.json").read_text())
        with self.assertRaises(RuntimePolicyUnavailable):RuntimePolicyProvider(self.client,FixtureRuntime,allowed_domains=("cybersecurity",))

    def test_external_unavailable_never_falls_back_to_private_local(self):
        self.server.close()
        with self.assertRaises(RuntimePolicyUnavailable):self.provider.authorize(self.principal,self.request())
        local=PublicOnlyLocalPolicy.build("public-user")
        with self.assertRaises(Exception):local.authorize(AuthenticatedPrincipal("public-user","public"),ClientScopeRequest(("privacy",),access_labels=(AccessLabel.PRIVATE,)))

    def test_local_public_mode_remains_explicit_and_separate(self):
        scope=PublicOnlyLocalPolicy.build("public-user").authorize(AuthenticatedPrincipal("public-user","public"),ClientScopeRequest(("cybersecurity",)))
        self.assertEqual(scope.policy_provider,"local");self.assertEqual(scope.access_labels,(AccessLabel.PUBLIC,))

if __name__=="__main__":unittest.main()
