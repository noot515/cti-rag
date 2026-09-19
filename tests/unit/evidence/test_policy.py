from __future__ import annotations

import pytest

from packages.evidence.policy import DenyByDefaultPolicy, PolicyDenied, Principal, PublicFixturePolicy, TrustedPrincipal, authorize_evidence_set
from packages.evidence.schema import AuthorizedEvidenceView, EvidencePolicyMetadata


def _principal() -> Principal:
    return Principal(principal_id="test-principal", source="trusted_local_cli")


def _policy() -> PublicFixturePolicy:
    return PublicFixturePolicy.trusted(source_allowlist=frozenset({"fixture-public"}))


def _view(scope: str = "public-fixture", **policy_overrides) -> AuthorizedEvidenceView:
    policy = EvidencePolicyMetadata(source_instances=("fixture-public",), **policy_overrides)
    return AuthorizedEvidenceView(evidence_uid="a" * 64, domain="cti", scope_id=scope,
                                  source_instances=("fixture-public",), policy=policy)


def test_trusted_principal_extends_principal_with_canonical_namespace():
    trusted = TrustedPrincipal(
        principal_id="test-principal",
        principal_namespace="user.id",
        source="trusted_local_cli",
    )
    assert TrustedPrincipal is not Principal
    assert isinstance(trusted, Principal)
    assert trusted.principal_namespace == "user.id"


def test_deny_by_default_has_no_implicit_scope():
    with pytest.raises(PolicyDenied, match="no corpus grant"):
        DenyByDefaultPolicy().resolve_scope(_principal(), "fixture-cti")


def test_public_fixture_policy_requires_trusted_construction_and_explicit_allowlist():
    with pytest.raises(PolicyDenied, match="trusted construction"):
        PublicFixturePolicy(corpus_id="fixture-cti", scope_id="public-fixture",
                            source_allowlist=frozenset({"fixture-public"}), _token=object())
    scope = _policy().resolve_scope(_principal(), "fixture-cti")
    assert scope.source_allowlist == frozenset({"fixture-public"})


def test_public_fixture_policy_requires_explicit_corpus_source_scope_and_destination():
    policy = _policy()
    scope = policy.resolve_scope(_principal(), "fixture-cti")
    assert policy.authorize_evidence(_view(), scope, "caller").allowed is True
    wrong_source = _view().model_copy(update={"source_instances": ("private-upstream",)})
    assert policy.authorize_evidence(wrong_source, scope, "caller").allowed is False
    assert policy.authorize_evidence(_view("other"), scope, "caller").allowed is False
    assert policy.authorize_evidence(_view(), scope, "embedding_provider").allowed is False
    assert policy.authorize_evidence(_view(), scope, "unregistered_destination").allowed is False
    assert authorize_evidence_set(policy, (_view(), _view()), scope, "caller").allowed
    assert not authorize_evidence_set(policy, (_view(), _view("other")), scope, "caller").allowed
    assert not authorize_evidence_set(policy, (), scope, "caller").allowed


def test_fixture_policy_fails_closed_on_unsupported_or_restricted_markings():
    policy = _policy()
    scope = policy.resolve_scope(_principal(), "fixture-cti")
    assert not policy.authorize_evidence(_view(unresolved_markings=True), scope, "caller").allowed
    assert not policy.authorize_evidence(_view(granular_selectors=("description",)), scope, "caller").allowed
    assert not policy.authorize_evidence(_view(dissemination=("tlp:amber",)), scope, "caller").allowed
    assert policy.authorize_evidence(_view(dissemination=("tlp:clear",)), scope, "caller").allowed


def test_public_fixture_policy_does_not_accept_request_selected_corpus():
    with pytest.raises(PolicyDenied, match="not the configured"):
        _policy().resolve_scope(_principal(), "caller-selected-private")
