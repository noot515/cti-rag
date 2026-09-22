"""Fail-closed local authorization provider for standalone/public deployments."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Tuple
from cti_rag.contracts import AccessLabel, PolicyLabels, ProcessingClass
from cti_rag.ports.models import ModelOperation
from cti_rag.ports.policy import AuthenticatedPrincipal, ClientScopeRequest, EffectiveScope, PolicyDenied, ProcessingDestination

@dataclass(frozen=True)
class PrincipalPolicy:
    principal_id:str
    tenant_id:str
    domains:Tuple[str,...]
    source_ids:Tuple[str,...]=()
    access_labels:Tuple[AccessLabel,...]=(AccessLabel.PUBLIC,)
    processing_classes:Tuple[ProcessingClass,...]=(ProcessingClass.LOCAL_ONLY,)
    allowed_model_destinations:Tuple[Tuple[str,Tuple[str,...]],...]=()
    private_state_allowed:bool=False
    def destinations_for(self,operation:str)->frozenset[str]:
        return frozenset(v for op,names in self.allowed_model_destinations if op==operation for v in names)

class LocalPolicyProvider:
    def __init__(self, rules:Tuple[PrincipalPolicy,...], epoch:int=1):
        if epoch < 1: raise ValueError("policy epoch must be positive")
        self._rules={r.principal_id:r for r in rules}; self._epoch=epoch
    @property
    def epoch(self): return self._epoch
    def replace_rules(self,rules:Tuple[PrincipalPolicy,...]):
        self._rules={r.principal_id:r for r in rules}; self._epoch += 1
    def authorize(self,principal:AuthenticatedPrincipal,requested:ClientScopeRequest)->EffectiveScope:
        rule=self._rules.get(principal.principal_id)
        if rule is None: raise PolicyDenied("principal has no local policy")
        if principal.tenant_id != rule.tenant_id: raise PolicyDenied("authenticated tenant does not match policy")
        requested_domains=requested.domains or rule.domains
        domains=tuple(sorted(set(requested_domains)&set(rule.domains)))
        if not domains: raise PolicyDenied("requested domains are not authorized")
        if requested.source_ids:
            allowed=set(rule.source_ids)
            if not allowed: raise PolicyDenied("explicit source access is not authorized")
            source_ids=tuple(sorted(set(requested.source_ids)&allowed))
            if not source_ids: raise PolicyDenied("requested sources are not authorized")
        else:
            source_ids=tuple(sorted(rule.source_ids))
        labels=tuple(sorted(set(requested.access_labels)&set(rule.access_labels),key=lambda x:x.value))
        if not labels: raise PolicyDenied("requested access labels are not authorized")
        if AccessLabel.PRIVATE in labels and not rule.private_state_allowed: raise PolicyDenied("private state is not authorized")
        return EffectiveScope(
            principal_id=principal.principal_id,tenant_id=rule.tenant_id,domains=domains,source_ids=source_ids,
            access_labels=labels,processing_classes=tuple(rule.processing_classes),policy_epoch=self._epoch,
            private_state_allowed=rule.private_state_allowed,
        )
    def authorize_model(self,scope:EffectiveScope,labels:PolicyLabels,operation:str,destination:ProcessingDestination)->None:
        rule=self._rules.get(scope.principal_id)
        if rule is None or rule.tenant_id != scope.tenant_id: raise PolicyDenied("policy unavailable for execution scope")
        if labels.tenant_id not in (scope.tenant_id,"public"): raise PolicyDenied("evidence tenant is outside effective scope")
        if labels.access_label not in scope.access_labels: raise PolicyDenied("evidence access label is outside effective scope")
        if labels.processing_class == ProcessingClass.LOCAL_ONLY and destination.remote: raise PolicyDenied("local-only evidence cannot be dispatched remotely")
        if labels.processing_class not in scope.processing_classes: raise PolicyDenied("processing class is not authorized")
        if destination.name not in rule.destinations_for(operation): raise PolicyDenied("model destination is not authorized for operation")

class PublicOnlyLocalPolicy(LocalPolicyProvider):
    @classmethod
    def build(cls,principal_id:str="public-local",domains:Tuple[str,...]=( "cybersecurity","networking","quant","privacy","humanities")):
        rule=PrincipalPolicy(
            principal_id=principal_id,tenant_id="public",domains=domains,access_labels=(AccessLabel.PUBLIC,),
            processing_classes=(ProcessingClass.LOCAL_ONLY,ProcessingClass.LOCAL_OR_APPROVED_REMOTE),
            allowed_model_destinations=tuple((op.value,("local",)) for op in ModelOperation),private_state_allowed=False,
        )
        return cls((rule,),epoch=1)
