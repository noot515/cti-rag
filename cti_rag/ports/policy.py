"""Authorization port and immutable execution-scope contracts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Protocol, Tuple
from cti_rag.contracts import AccessLabel, PolicyLabels, ProcessingClass

class PolicyDenied(PermissionError): pass
class PolicyUnavailable(RuntimeError): pass

@dataclass(frozen=True)
class AuthenticatedPrincipal:
    principal_id: str
    tenant_id: str
    authn_context: str = "authenticated"
    def __post_init__(self):
        if not self.principal_id.strip() or not self.tenant_id.strip(): raise ValueError("authenticated principal fields required")

@dataclass(frozen=True)
class ClientScopeRequest:
    domains: Tuple[str,...]
    source_ids: Tuple[str,...] = ()
    access_labels: Tuple[AccessLabel,...] = (AccessLabel.PUBLIC,)
    @classmethod
    def from_payload(cls, payload: Mapping[str, object]):
        # Deliberately whitelist only narrowing fields. Client principal/tenant/clearance fields are ignored.
        domains=tuple(str(v) for v in payload.get("domains", ()) if str(v).strip())
        sources=tuple(str(v) for v in payload.get("source_ids", ()) if str(v).strip())
        labels=[]
        for value in payload.get("access_labels", (AccessLabel.PUBLIC.value,)):
            try: labels.append(AccessLabel(str(value)))
            except ValueError: continue
        return cls(domains=domains, source_ids=sources, access_labels=tuple(labels or [AccessLabel.PUBLIC]))

@dataclass(frozen=True)
class EffectiveScope:
    principal_id: str
    tenant_id: str
    domains: Tuple[str,...]
    source_ids: Tuple[str,...]
    access_labels: Tuple[AccessLabel,...]
    processing_classes: Tuple[ProcessingClass,...]
    policy_epoch: int
    private_state_allowed: bool = False
    def __post_init__(self):
        if not self.domains: raise PolicyDenied("effective scope contains no authorized domains")

@dataclass(frozen=True)
class ProcessingDestination:
    name: str
    remote: bool
    def __post_init__(self):
        if not self.name.strip(): raise ValueError("destination name required")

class PolicyPort(Protocol):
    def authorize(self, principal: AuthenticatedPrincipal, requested: ClientScopeRequest) -> EffectiveScope: ...
    def authorize_model(self, scope: EffectiveScope, labels: PolicyLabels, operation: str, destination: ProcessingDestination) -> None: ...
