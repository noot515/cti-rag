"""Fail-closed local authorization provider for standalone/public deployments."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple
from cti_rag.contracts import AccessLabel, PolicyLabels, ProcessingClass
from cti_rag.ports.models import ModelOperation
from cti_rag.ports.policy import AuthenticatedPrincipal, ClientScopeRequest, EffectiveScope, NetworkDestination, PolicyDenied, ProcessingDestination

@dataclass(frozen=True)
class PrincipalPolicy:
    principal_id:str
    tenant_id:str
    domains:Tuple[str,...]
    source_ids:Tuple[str,...]=()
    access_labels:Tuple[AccessLabel,...]=(AccessLabel.PUBLIC,)
    processing_classes:Tuple[ProcessingClass,...]=(ProcessingClass.LOCAL_ONLY,)
    allowed_model_destinations:Tuple[Tuple[str,Tuple[str,...]],...]=()
    allowed_network_destinations:Tuple[Tuple[str,Tuple[str,...]],...]=()
    private_state_allowed:bool=False
    debug_traces_allowed:bool=False
    def destinations_for(self,operation:str)->frozenset[str]:
        return frozenset(v for op,names in self.allowed_model_destinations if op==operation for v in names)
    def network_destinations_for(self,purpose:str)->frozenset[str]:
        return frozenset(v for op,names in self.allowed_network_destinations if op==purpose for v in names)

class LocalPolicyProvider:
    def __init__(self,rules:Tuple[PrincipalPolicy,...],epoch:int=1):
        if epoch<1:raise ValueError("policy epoch must be positive")
        self._rules={r.principal_id:r for r in rules};self._epoch=epoch
    @property
    def epoch(self):return self._epoch
    def replace_rules(self,rules:Tuple[PrincipalPolicy,...]):
        self._rules={r.principal_id:r for r in rules};self._epoch+=1
    def authorize(self,principal:AuthenticatedPrincipal,requested:ClientScopeRequest)->EffectiveScope:
        rule=self._rules.get(principal.principal_id)
        if rule is None:raise PolicyDenied("principal has no local policy")
        if principal.tenant_id!=rule.tenant_id:raise PolicyDenied("authenticated tenant does not match policy")
        requested_domains=requested.domains or rule.domains
        domains=tuple(sorted(set(requested_domains)&set(rule.domains)))
        if not domains:raise PolicyDenied("requested domains are not authorized")
        if requested.source_ids:
            allowed=set(rule.source_ids)
            if not allowed:raise PolicyDenied("explicit source access is not authorized")
            source_ids=tuple(sorted(set(requested.source_ids)&allowed))
            if not source_ids:raise PolicyDenied("requested sources are not authorized")
        else:source_ids=tuple(sorted(rule.source_ids))
        labels=tuple(sorted(set(requested.access_labels)&set(rule.access_labels),key=lambda x:x.value))
        if not labels:raise PolicyDenied("requested access labels are not authorized")
        if AccessLabel.PRIVATE in labels and not rule.private_state_allowed:raise PolicyDenied("private state is not authorized")
        requested_processing=requested.processing_classes or rule.processing_classes
        processing=tuple(sorted(set(requested_processing)&set(rule.processing_classes),key=lambda x:x.value))
        if not processing:raise PolicyDenied("requested processing classes are not authorized")
        return EffectiveScope(principal.principal_id,rule.tenant_id,domains,source_ids,labels,processing,self._epoch,rule.private_state_allowed,rule.debug_traces_allowed,"local",None,None,None,requested.purpose)
    def revalidate_for_response(self,scope,principal,requested):
        current=self.authorize(principal,requested)
        if current.principal_id!=scope.principal_id or current.tenant_id!=scope.tenant_id:raise PolicyDenied("response principal changed")
        return current
    def _rule_for(self,scope):
        rule=self._rules.get(scope.principal_id)
        if rule is None or rule.tenant_id!=scope.tenant_id:raise PolicyDenied("policy unavailable for execution scope")
        return rule
    @staticmethod
    def _check_labels(scope,labels):
        if labels.tenant_id not in (scope.tenant_id,"public"):raise PolicyDenied("payload tenant is outside effective scope")
        if labels.access_label not in scope.access_labels:raise PolicyDenied("payload access label is outside effective scope")
        if labels.processing_class not in scope.processing_classes:raise PolicyDenied("processing class is not authorized")
    def authorize_model(self,scope:EffectiveScope,labels:PolicyLabels,operation:str,destination:ProcessingDestination)->None:
        rule=self._rule_for(scope);self._check_labels(scope,labels)
        if labels.processing_class==ProcessingClass.LOCAL_ONLY and destination.remote:raise PolicyDenied("local-only evidence cannot be dispatched remotely")
        if destination.name not in rule.destinations_for(operation):raise PolicyDenied("model destination is not authorized for operation")
    def authorize_network(self,scope:EffectiveScope,labels:PolicyLabels,purpose:str,destination:NetworkDestination)->None:
        rule=self._rule_for(scope);self._check_labels(scope,labels)
        if labels.processing_class==ProcessingClass.LOCAL_ONLY and destination.remote:raise PolicyDenied("local-only data cannot be dispatched remotely")
        if destination.name not in rule.network_destinations_for(purpose):raise PolicyDenied("network destination is not authorized for purpose")

class PublicOnlyLocalPolicy(LocalPolicyProvider):
    @classmethod
    def build(cls,principal_id:str="public-local",domains:Tuple[str,...]=("cybersecurity","networking","quant","privacy","humanities")):
        rule=PrincipalPolicy(principal_id=principal_id,tenant_id="public",domains=domains,access_labels=(AccessLabel.PUBLIC,),processing_classes=(ProcessingClass.LOCAL_ONLY,ProcessingClass.LOCAL_OR_APPROVED_REMOTE),allowed_model_destinations=tuple((op.value,("local",)) for op in ModelOperation),allowed_network_destinations=(),private_state_allowed=False,debug_traces_allowed=False)
        return cls((rule,),epoch=1)
