"""Fail-closed authorization boundary for advanced evidence retrieval."""
from __future__ import annotations

from typing import Iterable, Literal, Protocol
from pydantic import Field

from .schema import AuthorizedEvidenceView, EvidenceModel

Destination = Literal[
    "caller",
    "local_generator",
    "embedding_provider",
    "reranker_provider",
    "debug_trace",
]


class Principal(EvidenceModel):
    principal_id: str = Field(min_length=1)
    source: Literal["authenticated_api", "trusted_local_cli"]
    capabilities: frozenset[str] = frozenset()


class TrustedPrincipal(Principal):
    """Canonical principal whose ID namespace was established by a trusted boundary."""

    principal_namespace: str = Field(min_length=1)


class ResolvedScope(EvidenceModel):
    principal_id: str = Field(min_length=1)
    principal_namespace: str | None = None
    corpus_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    active_catalog_id: str | None = None
    policy_version: str = Field(min_length=1)
    source_allowlist: frozenset[str]
    allowed_destinations: frozenset[str] = frozenset()


AuthorizedScope = ResolvedScope


class PolicyDecision(EvidenceModel):
    allowed: bool
    reason: str = Field(min_length=1)


class RetrievalPolicy(Protocol):
    policy_version: str

    def resolve_scope(self, principal: Principal, corpus: str) -> ResolvedScope: ...

    def authorize_evidence(
        self,
        view: AuthorizedEvidenceView,
        scope: ResolvedScope,
        destination: str,
    ) -> PolicyDecision: ...


class PolicyDenied(PermissionError):
    pass


class DenyByDefaultPolicy:
    policy_version = "deny-by-default-v1"

    def resolve_scope(self, principal: Principal, corpus: str) -> ResolvedScope:
        raise PolicyDenied("no corpus grant exists under deny-by-default policy")

    def authorize_evidence(
        self,
        view: AuthorizedEvidenceView,
        scope: ResolvedScope,
        destination: str,
    ) -> PolicyDecision:
        return PolicyDecision(allowed=False, reason="deny-by-default")


class PublicFixturePolicy:
    """Explicitly trusted policy for deterministic public/synthetic fixtures only."""

    policy_version = "public-fixture-v2"
    _TRUSTED = object()

    def __init__(
        self,
        *,
        corpus_id: str,
        scope_id: str,
        source_allowlist: frozenset[str],
        _token: object,
    ) -> None:
        if _token is not self._TRUSTED:
            raise PolicyDenied("PublicFixturePolicy requires trusted construction")
        if not source_allowlist:
            raise PolicyDenied("PublicFixturePolicy requires an explicit source allowlist")
        self.corpus_id = corpus_id
        self.scope_id = scope_id
        self.source_allowlist = source_allowlist
        self.allowed_destinations = frozenset({"caller", "local_generator"})

    @classmethod
    def trusted(
        cls,
        *,
        corpus_id: str = "fixture-cti",
        scope_id: str = "public-fixture",
        source_allowlist: frozenset[str],
    ) -> "PublicFixturePolicy":
        return cls(
            corpus_id=corpus_id,
            scope_id=scope_id,
            source_allowlist=source_allowlist,
            _token=cls._TRUSTED,
        )

    def resolve_scope(self, principal: Principal, corpus: str) -> ResolvedScope:
        if principal.source not in {"authenticated_api", "trusted_local_cli"}:
            raise PolicyDenied("untrusted principal source")
        if corpus != self.corpus_id:
            raise PolicyDenied(
                "requested corpus is not the configured public fixture corpus"
            )
        namespace = (
            principal.principal_namespace
            if isinstance(principal, TrustedPrincipal)
            else None
        )
        return ResolvedScope(
            principal_id=principal.principal_id,
            principal_namespace=namespace,
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
        scope: ResolvedScope,
        destination: str,
    ) -> PolicyDecision:
        if destination not in {
            "caller",
            "local_generator",
            "embedding_provider",
            "reranker_provider",
            "debug_trace",
        }:
            return PolicyDecision(allowed=False, reason="unknown-destination")
        if view.domain != scope.domain or view.scope_id != scope.scope_id:
            return PolicyDecision(allowed=False, reason="domain-or-scope-mismatch")
        if not view.source_instances or not set(view.source_instances).issubset(
            scope.source_allowlist
        ):
            return PolicyDecision(
                allowed=False,
                reason="source-not-on-public-fixture-allowlist",
            )
        if destination not in scope.allowed_destinations:
            return PolicyDecision(allowed=False, reason="destination-not-permitted")
        metadata = view.policy
        if metadata.unresolved_markings or metadata.granular_selectors:
            return PolicyDecision(
                allowed=False,
                reason="unresolved-or-granular-marking",
            )
        dissemination = set(metadata.dissemination)
        if dissemination and dissemination != {"tlp:clear"}:
            return PolicyDecision(
                allowed=False,
                reason="fixture-policy-only-allows-tlp-clear",
            )
        return PolicyDecision(
            allowed=True,
            reason="explicit-public-fixture-contract",
        )


def authorize_evidence_set(
    policy: RetrievalPolicy,
    views: Iterable[AuthorizedEvidenceView],
    scope: ResolvedScope,
    destination: str,
) -> PolicyDecision:
    """Authorize every component of a compound result such as a graph path."""
    checked = False
    for view in views:
        checked = True
        decision = policy.authorize_evidence(view, scope, destination)
        if not decision.allowed:
            return decision
    if not checked:
        return PolicyDecision(
            allowed=False,
            reason="no-evidence-components-authorized",
        )
    return PolicyDecision(
        allowed=True,
        reason="all-evidence-components-authorized",
    )


def require_authorized(decision: PolicyDecision) -> None:
    if not decision.allowed:
        raise PolicyDenied(decision.reason)


__all__ = [
    "AuthorizedScope",
    "DenyByDefaultPolicy",
    "Destination",
    "PolicyDecision",
    "PolicyDenied",
    "Principal",
    "PublicFixturePolicy",
    "ResolvedScope",
    "RetrievalPolicy",
    "TrustedPrincipal",
    "authorize_evidence_set",
    "require_authorized",
]
