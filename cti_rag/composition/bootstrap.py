"""Explicit composition roots; optional SDK adapters are injected, never imported here."""
from dataclasses import dataclass, field
from typing import Mapping, Optional
from cti_rag.domains.registry import DomainRegistry,builtin_registry
from cti_rag.policy.local import PublicOnlyLocalPolicy
@dataclass(frozen=True)
class RuntimeComponents:
    domains:DomainRegistry
    policy:object
    search_ports:Mapping[str,object]=field(default_factory=dict)
    graph_port:Optional[object]=None
    structured_port:Optional[object]=None
    evidence_store:Optional[object]=None
    snapshot_catalog:Optional[object]=None
    model_ports:Mapping[str,object]=field(default_factory=dict)
    web_search_provider:Optional[object]=None
    web_fetch_port:Optional[object]=None
def build_public_only_runtime(principal_id="public-local",**overrides):
    domains=overrides.pop("domains",builtin_registry()); policy=overrides.pop("policy",PublicOnlyLocalPolicy.build(principal_id,domains.names()))
    return RuntimeComponents(domains=domains,policy=policy,**overrides)
