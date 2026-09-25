"""Optional adapter from PolicyPort to the canonical respectful-runtime broker.

The backend package is imported lazily. This module does not reimplement the
RuntimePolicy decision kernel or invent a network endpoint: it uses the canonical
Unix-domain AuthorityClient protocol pinned in runtimepolicy_pin.json.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
import time
import uuid

from cti_rag.contracts import AccessLabel,PolicyLabels,ProcessingClass
from cti_rag.ports.policy import (
    AuthenticatedPrincipal,ClientScopeRequest,EffectiveScope,NetworkDestination,
    PolicyDenied,PolicyUnavailable,ProcessingDestination,
)

_PIN_PATH=Path(__file__).with_name("runtimepolicy_pin.json")

class RuntimePolicyUnavailable(PolicyUnavailable):pass
class RuntimePolicyDenied(PolicyDenied):pass

@dataclass(frozen=True)
class _Admission:
    action:object
    record:object
    assessment:object
    principal:AuthenticatedPrincipal
    requested:ClientScopeRequest

def _load_pin():
    data=json.loads(_PIN_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version")!="runtimepolicy-pin/1":raise RuntimePolicyUnavailable("unsupported RuntimePolicy pin schema")
    return data

def _csv_enum(value,enum_type,default):
    raw=(value or "").strip()
    if not raw:return tuple(default)
    out=[]
    for item in raw.split(","):
        try:out.append(enum_type(item.strip()))
        except ValueError as exc:raise RuntimePolicyUnavailable(f"invalid configured {enum_type.__name__}") from exc
    return tuple(dict.fromkeys(out))

class RuntimePolicyProvider:
    """Fail-closed PolicyPort provider backed by an operator-owned broker."""

    def __init__(
        self,client,runtime_module,*,allowed_domains=(),allowed_sources=None,
        allowed_access_labels=(AccessLabel.PUBLIC,),
        allowed_processing_classes=(ProcessingClass.LOCAL_ONLY,),
        private_state_allowed=False,debug_traces_allowed=False,
        expected_artifact_sha256=None,pin=None,
    ):
        self.client=client;self.rt=runtime_module;self.pin=pin or _load_pin()
        self.allowed_domains=tuple(dict.fromkeys(str(v) for v in allowed_domains if str(v).strip()))
        self.allowed_sources=None if allowed_sources is None else tuple(dict.fromkeys(str(v) for v in allowed_sources if str(v).strip()))
        self.allowed_access_labels=tuple(dict.fromkeys(allowed_access_labels))
        self.allowed_processing_classes=tuple(dict.fromkeys(allowed_processing_classes))
        self.private_state_allowed=bool(private_state_allowed);self.debug_traces_allowed=bool(debug_traces_allowed)
        self.expected_artifact_sha256=expected_artifact_sha256
        self._admissions={}
        self._verify_runtime_package();self._verify_compatibility()

    @classmethod
    def from_environment(cls):
        socket_path=os.getenv("RESPECTFUL_BROKER_SOCKET")
        if not socket_path:raise RuntimePolicyUnavailable("RESPECTFUL_BROKER_SOCKET is required for external RuntimePolicy mode")
        try:
            timeout=float(os.getenv("CTI_RAG_RUNTIMEPOLICY_TIMEOUT_SECONDS","5"))
        except ValueError as exc:raise RuntimePolicyUnavailable("invalid RuntimePolicy timeout") from exc
        if not 0.1<=timeout<=30:raise RuntimePolicyUnavailable("RuntimePolicy timeout must be between 0.1 and 30 seconds")
        runtime=importlib.import_module("respectful_runtime")
        uid=os.getenv("RESPECTFUL_BROKER_UID")
        expected_uid=None if uid in (None,"") else int(uid)
        client=runtime.AuthorityClient(socket_path,expected_uid=expected_uid,timeout=timeout,protocol_version=3)
        domains=tuple(v.strip() for v in os.getenv("CTI_RAG_RUNTIMEPOLICY_DOMAINS","cybersecurity,networking,quant,privacy,humanities").split(",") if v.strip())
        sources_raw=os.getenv("CTI_RAG_RUNTIMEPOLICY_SOURCE_IDS")
        sources=None if sources_raw is None else tuple(v.strip() for v in sources_raw.split(",") if v.strip())
        labels=_csv_enum(os.getenv("CTI_RAG_RUNTIMEPOLICY_ACCESS_LABELS"),AccessLabel,(AccessLabel.PUBLIC,))
        processing=_csv_enum(os.getenv("CTI_RAG_RUNTIMEPOLICY_PROCESSING_CLASSES"),ProcessingClass,(ProcessingClass.LOCAL_ONLY,))
        return cls(
            client,runtime,allowed_domains=domains,allowed_sources=sources,
            allowed_access_labels=labels,allowed_processing_classes=processing,
            private_state_allowed=os.getenv("CTI_RAG_RUNTIMEPOLICY_PRIVATE_STATE","0").lower() in ("1","true","yes","on"),
            debug_traces_allowed=os.getenv("CTI_RAG_RUNTIMEPOLICY_DEBUG_TRACES","0").lower() in ("1","true","yes","on"),
            expected_artifact_sha256=os.getenv("CTI_RAG_RUNTIMEPOLICY_EXPECTED_ARTIFACT_SHA256") or None,
        )

    def _verify_runtime_package(self):
        expected=self.pin["contract"]
        if getattr(self.rt,"VERSION",None)!=expected["wire_version"]:raise RuntimePolicyUnavailable("RuntimePolicy wire contract version mismatch")
        if getattr(self.rt,"RUNTIME_VERSION",None)!=expected["runtime_version"]:raise RuntimePolicyUnavailable("RuntimePolicy runtime version mismatch")
        if getattr(self.rt,"BROKER_PROTOCOL_VERSION",None)!=expected["broker_protocol_version"]:raise RuntimePolicyUnavailable("RuntimePolicy broker protocol mismatch")

    def _verify_compatibility(self):
        try:value=self.client.compatibility()
        except Exception as exc:raise RuntimePolicyUnavailable(f"RuntimePolicy compatibility unavailable: {type(exc).__name__}") from exc
        required={"contract_version","runtime_version","broker_protocol_version","default_broker_protocol_version","supported_broker_protocol_versions","capabilities","broker_epoch"}
        optional={"runtime_artifact_manifest_sha256"}
        if type(value) is not dict or not required.issubset(value) or set(value)-required-optional:
            raise RuntimePolicyUnavailable("invalid RuntimePolicy compatibility response schema")
        expected=self.pin["contract"]
        if value["contract_version"]!=expected["wire_version"] or value["runtime_version"]!=expected["runtime_version"] or value["broker_protocol_version"]!=expected["broker_protocol_version"]:
            raise RuntimePolicyUnavailable("RuntimePolicy compatibility identity mismatch")
        if type(value["broker_epoch"]) is not str or not value["broker_epoch"]:raise RuntimePolicyUnavailable("invalid RuntimePolicy broker epoch")
        supported=value["supported_broker_protocol_versions"]
        if type(supported) is not list or any(type(v) is not int for v in supported) or expected["broker_protocol_version"] not in supported:
            raise RuntimePolicyUnavailable("invalid RuntimePolicy supported protocol list")
        capabilities=value["capabilities"]
        if type(capabilities) is not list or any(type(v) is not str for v in capabilities):
            raise RuntimePolicyUnavailable("invalid RuntimePolicy capability list")
        manifest=value.get("runtime_artifact_manifest_sha256")
        if manifest is not None and (type(manifest) is not str or len(manifest)!=64 or any(ch not in "0123456789abcdef" for ch in manifest)):
            raise RuntimePolicyUnavailable("invalid RuntimePolicy artifact attestation")
        if self.expected_artifact_sha256 is not None and manifest!=self.expected_artifact_sha256:
            raise RuntimePolicyUnavailable("RuntimePolicy installed artifact attestation mismatch")
        return value

    @staticmethod
    def _label_payload(labels):
        return {
            "tenant_id":labels.tenant_id,"access_label":labels.access_label.value,
            "processing_class":labels.processing_class.value,"license_id":labels.license_id,
            "retention_class":labels.retention_class,"markings":list(labels.markings),
        }

    def _scope_candidate(self,principal,requested):
        if not isinstance(principal,AuthenticatedPrincipal) or not isinstance(requested,ClientScopeRequest):
            raise RuntimePolicyDenied("typed principal and scope request are required")
        domains=tuple(dict.fromkeys(requested.domains))
        if self.allowed_domains:
            domains=tuple(v for v in domains if v in self.allowed_domains)
        if not domains or len(domains)!=len(tuple(dict.fromkeys(requested.domains))):
            raise RuntimePolicyDenied("requested domain lies outside configured RuntimePolicy ceiling")
        sources=tuple(dict.fromkeys(requested.source_ids))
        if self.allowed_sources is not None and any(v not in self.allowed_sources for v in sources):
            raise RuntimePolicyDenied("requested source lies outside configured RuntimePolicy ceiling")
        labels=tuple(dict.fromkeys(requested.access_labels))
        if not labels or any(v not in self.allowed_access_labels for v in labels):
            raise RuntimePolicyDenied("requested access label lies outside configured RuntimePolicy ceiling")
        if AccessLabel.PRIVATE in labels and not self.private_state_allowed:
            raise RuntimePolicyDenied("private state is disabled for this RuntimePolicy provider")
        wanted=requested.processing_classes or self.allowed_processing_classes
        processing=tuple(dict.fromkeys(wanted))
        if not processing or any(v not in self.allowed_processing_classes for v in processing):
            raise RuntimePolicyDenied("requested processing class lies outside configured RuntimePolicy ceiling")
        return domains,sources,labels,processing

    def _assess(self,operation,target,payload):
        try:
            self._verify_compatibility()
            revision=self.client.current_revision()
            if type(revision) is not str or not revision.strip():raise RuntimePolicyUnavailable("invalid RuntimePolicy state revision")
            action=self.rt.Action.for_payload(uuid.uuid4().hex,operation,target,payload)
            self.client.register_request(action,payload=payload,host="research",details={"cti_rag_policy_adapter":"1"},mutates_state=False)
            assessment=self.client(action)
            if not isinstance(assessment,self.rt.Assessment):raise RuntimePolicyUnavailable("RuntimePolicy returned an untyped assessment")
            if assessment.schema_version!=self.pin["contract"]["wire_version"] or assessment.action!=action or assessment.state_revision!=revision:
                raise RuntimePolicyUnavailable("RuntimePolicy assessment binding mismatch")
            record=self.rt.RuntimePolicy().evaluate(action,assessment,int(getattr(self.client,"clock",time.time)()))
            self.client.audit(record)
            if record.decision!="act":
                raise RuntimePolicyDenied("RuntimePolicy "+record.decision+": "+",".join(record.reasons))
            self.client.check(action,record)
            return action,record,assessment
        except RuntimePolicyDenied:
            raise
        except RuntimePolicyUnavailable:
            raise
        except Exception as exc:
            raise RuntimePolicyUnavailable(f"RuntimePolicy unavailable or invalid: {type(exc).__name__}") from exc

    def authorize(self,principal:AuthenticatedPrincipal,requested:ClientScopeRequest)->EffectiveScope:
        domains,sources,labels,processing=self._scope_candidate(principal,requested)
        payload={
            "schema_version":"cti-rag-policy-request/1",
            "principal":{"principal_id":principal.principal_id,"tenant_id":principal.tenant_id,"authn_context":principal.authn_context},
            "operation":"retrieve_evidence","purpose":requested.purpose,
            "requested_scope":{"domains":list(domains),"source_ids":list(sources),"access_labels":[v.value for v in labels],"processing_classes":[v.value for v in processing]},
            "destination":{"kind":"response","name":"requesting_principal","remote":False},
        }
        action,record,assessment=self._assess("cti_rag.policy.scope","cti-rag:retrieval-scope",payload)
        scope=EffectiveScope(
            principal.principal_id,principal.tenant_id,domains,sources,labels,processing,
            assessment.state_revision,self.private_state_allowed,self.debug_traces_allowed,
            "runtimepolicy",assessment.expires_at,assessment.assessment_id,action.fingerprint,requested.purpose,
        )
        self._admissions[action.fingerprint]=_Admission(action,record,assessment,principal,requested)
        return scope

    def _revalidate_scope(self,scope,principal=None,requested=None):
        if scope.policy_provider!="runtimepolicy" or not scope.admission_action_fingerprint:
            raise RuntimePolicyDenied("scope was not issued by RuntimePolicy provider")
        admission=self._admissions.get(scope.admission_action_fingerprint)
        if admission is None:raise RuntimePolicyDenied("RuntimePolicy admission is not available for replay")
        if principal is not None and principal!=admission.principal:raise RuntimePolicyDenied("response principal differs from admitted principal")
        if requested is not None and requested!=admission.requested:raise RuntimePolicyDenied("response request differs from admitted request")
        try:
            self._verify_compatibility()
            if self.client.current_revision()!=admission.assessment.state_revision:raise RuntimePolicyDenied("RuntimePolicy state revision changed")
            if int(getattr(self.client,"clock",time.time)())>=admission.assessment.expires_at:raise RuntimePolicyDenied("RuntimePolicy assessment expired")
            self.client.check(admission.action,admission.record)
        except RuntimePolicyDenied:raise
        except Exception as exc:raise RuntimePolicyUnavailable(f"RuntimePolicy response revalidation unavailable: {type(exc).__name__}") from exc
        return scope

    def revalidate_for_response(self,scope,principal,requested):
        return self._revalidate_scope(scope,principal,requested)

    @staticmethod
    def _check_labels(scope,labels):
        if labels.tenant_id not in (scope.tenant_id,"public"):raise RuntimePolicyDenied("payload tenant outside admitted scope")
        if labels.access_label not in scope.access_labels:raise RuntimePolicyDenied("payload access label outside admitted scope")
        if labels.processing_class not in scope.processing_classes:raise RuntimePolicyDenied("payload processing class outside admitted scope")

    def authorize_model(self,scope,labels:PolicyLabels,operation:str,destination:ProcessingDestination)->None:
        self._check_labels(scope,labels);self._revalidate_scope(scope)
        if labels.processing_class==ProcessingClass.LOCAL_ONLY and destination.remote:raise RuntimePolicyDenied("local-only evidence cannot be dispatched remotely")
        payload={
            "schema_version":"cti-rag-policy-request/1","operation":operation,"purpose":scope.purpose,
            "parent_scope":{"action_fingerprint":scope.admission_action_fingerprint,"state_revision":scope.policy_epoch},
            "classification":self._label_payload(labels),
            "destination":{"kind":"model","name":destination.name,"remote":destination.remote},
        }
        self._assess("cti_rag.policy.model",f"model:{destination.name}",payload)

    def authorize_network(self,scope,labels:PolicyLabels,purpose:str,destination:NetworkDestination)->None:
        self._check_labels(scope,labels);self._revalidate_scope(scope)
        if labels.processing_class==ProcessingClass.LOCAL_ONLY and destination.remote:raise RuntimePolicyDenied("local-only data cannot be dispatched remotely")
        payload={
            "schema_version":"cti-rag-policy-request/1","operation":"network_access","purpose":purpose,
            "parent_scope":{"action_fingerprint":scope.admission_action_fingerprint,"state_revision":scope.policy_epoch},
            "classification":self._label_payload(labels),
            "destination":{"kind":"network","name":destination.name,"endpoint":destination.endpoint,"remote":destination.remote},
        }
        self._assess("cti_rag.policy.network",f"network:{destination.name}",payload)
