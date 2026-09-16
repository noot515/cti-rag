"""Fail-closed authorization boundary for advanced evidence retrieval."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import Field

from .schema import AuthorizedEvidenceView, EvidenceModel

Destination = Literal[
    "caller",
    "local_generator",
    "embedding_provider",
    "reranker_provider",
    "debug_trace",
]


class TrustedPrincipal(EvidenceModel):
    principal_id: str = Field(min_length=1)
    source: Literal["authenticated_api", "trusted_local_cli"]
    capabilities: frozenset[str] = frozenset()


class AuthorizedScope(EvidenceModel):
    principal_id: str = Field(min_length=1)
    corpus_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    source_allowlist: frozenset[str] = frozenset()
    allowed_destinations: frozenset[str] = frozenset()


class PolicyDecision(EvidenceModel):
    allowed: bool
    reason: str = Field(min_length=1)


class RetrievalPolicy(Protocol):
    policy_version: str

    def resolve_scope(self, principal: TrustedPrincipal, corpus: str) -> AuthorizedScope: ...

    def authorize_evidence(
        self,
        view: AuthorizedEvidenceView,
        scope: AuthorizedScope,
        destination: Destination,
    ) -> PolicyDecision: ...


class PolicyDenied(PermissionError):
    pass


class DenyByDefaultPolicy:
    policy_version = "deny-by-default-v1"

    def resolve_scope(self, principal: TrustedPrincipal, corpus: str) -> AuthorizedScope:
        raise PolicyDenied("no corpus grant exists under deny-by-default policy")

    def authorize_evidence(
        self,
        view: AuthorizedEvidenceView,
        scope: AuthorizedScope,
        destination: Destination,
    ) -> PolicyDecision:
        return PolicyDecision(allowed=False, reason="deny-by-default")


class PublicFixturePolicy:
    """Explicit policy for deterministic synthetic/public fixture tests only."""

    policy_version = "public-fixture-v1"

    def __init__(
        self,
        *,
        corpus_id: str = "fixture-cti",
        scope_id: str = "public-fixture",
        source_allowlist: frozenset[str] = frozenset({"fixture-public"}),
    ) -> None:
        self.corpus_id = corpus_id
        self.scope_id = scope_id
        self.source_allowlist = source_allowlist
        self.allowed_destinations = frozenset({"caller", "local_generator"})

    def resolve_scope(self, principal: TrustedPrincipal, corpus: str) -> AuthorizedScope:
        if corpus != self.corpus_id:
            raise PolicyDenied("requested corpus is not the configured public fixture corpus")
        return AuthorizedScope(
            principal_id=principal.principal_id,
            corpus_id=corpus,
            domain="cti",
            scope_id=self.scope_id,
            policy_version=self.policy_version,
            source_allowlist=self.source_allowlist,
            allowed_destinations=self.allowed_destinations,
        )

    def authorize_evidence(
        self,
        view: AuthorizedEvidenceView,
        scope: AuthorizedScope,
        destination: Destination,
    ) -> PolicyDecision:
        if view.domain != scope.domain or view.scope_id != scope.scope_id:
            return PolicyDecision(allowed=False, reason="domain-or-scope-mismatch")
        if not view.source_instances or not set(view.source_instances).issubset(scope.source_allowlist):
            return PolicyDecision(allowed=False, reason="source-not-on-public-fixture-allowlist")
        if destination not in scope.allowed_destinations:
            return PolicyDecision(allowed=False, reason="destination-not-permitted")
        metadata = view.policy
        if metadata.unresolved_markings or metadata.granular_selectors:
            return PolicyDecision(allowed=False, reason="unresolved-or-granular-marking")
        dissemination = set(metadata.dissemination)
        if dissemination and dissemination != {"tlp:clear"}:
            return PolicyDecision(allowed=False, reason="fixture-policy-only-allows-tlp-clear")
        return PolicyDecision(allowed=True, reason="explicit-public-fixture-contract")


def require_authorized(decision: PolicyDecision) -> None:
    if not decision.allowed:
        raise PolicyDenied(decision.reason)


__all__ = [
    "AuthorizedScope",
    "DenyByDefaultPolicy",
    "Destination",
    "PolicyDecision",
    "PolicyDenied",
    "PublicFixturePolicy",
    "RetrievalPolicy",
    "TrustedPrincipal",
    "require_authorized",
]
