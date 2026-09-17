from __future__ import annotations

import pytest
import yaml

from packages.evidence.access import (
    CorpusAccessDenied,
    CorpusAccessStore,
    CorpusAccessUnavailable,
    CorpusGrant,
    CorpusGrantPolicy,
    CorpusRegistrationManifest,
)
from packages.evidence.cli import register_corpus
from packages.evidence.policy import TrustedPrincipal
from packages.evidence.schema import AuthorizedEvidenceView, EvidencePolicyMetadata


def admin():
    return TrustedPrincipal(
        principal_id="operator",
        principal_namespace="local-admin",
        source="trusted_local_cli",
        capabilities=frozenset({"corpus:register"}),
    )


def user(identifier):
    return TrustedPrincipal(
        principal_id=str(identifier),
        principal_namespace="user.id",
        source="authenticated_api",
    )


def manifest(*grants, policy_version="p1"):
    return CorpusRegistrationManifest(
        corpus_key="public-cti",
        domain="cti",
        scope_id="scope-a",
        active_catalog_id="catalog-a",
        policy_version=policy_version,
        source_allowlist=frozenset({"fixture"}),
        allowed_destinations=frozenset({"caller", "reranker_provider"}),
        grants=tuple(
            CorpusGrant(
                principal_namespace="user.id",
                principal_id=str(grant),
            )
            for grant in grants
        ),
    )


def test_two_tenants_and_legacy_id_does_not_grant(tmp_path):
    with CorpusAccessStore(tmp_path / "access.sqlite") as store:
        store.register_corpus(manifest(1), actor=admin())
        scope = store.resolve_scope(user(1), "public-cti")
        assert scope.principal_id == "1"
        assert scope.principal_namespace == "user.id"
        assert scope.active_catalog_id == "catalog-a"
        with pytest.raises(CorpusAccessDenied, match="corpus-access-denied"):
            store.resolve_scope(user(2), "public-cti")


def test_unknown_and_ownerless_corpus_are_indistinguishable(tmp_path):
    with CorpusAccessStore(tmp_path / "access.sqlite") as store:
        with pytest.raises(CorpusAccessDenied) as unknown:
            store.resolve_scope(user(1), "missing")
        store.register_corpus(manifest(), actor=admin())
        with pytest.raises(CorpusAccessDenied) as ownerless:
            store.resolve_scope(user(1), "public-cti")
        assert str(unknown.value) == str(ownerless.value) == "corpus-access-denied"


def test_revoked_grant_and_policy_change_invalidate_pinned_scope(tmp_path):
    with CorpusAccessStore(tmp_path / "access.sqlite") as store:
        store.register_corpus(manifest(1), actor=admin())
        principal = user(1)
        scope = store.resolve_scope(principal, "public-cti")
        policy = CorpusGrantPolicy(store, principal)
        view = AuthorizedEvidenceView(
            evidence_uid="1" * 64,
            domain="cti",
            scope_id="scope-a",
            source_instances=("fixture",),
            policy=EvidencePolicyMetadata(),
        )
        assert policy.authorize_evidence(view, scope, "caller").allowed
        store.revoke_grant(
            corpus_key="public-cti",
            principal_namespace="user.id",
            principal_id="1",
            actor=admin(),
        )
        assert not policy.authorize_evidence(view, scope, "caller").allowed

        store.register_corpus(manifest(1, policy_version="p2"), actor=admin())
        with pytest.raises(CorpusAccessDenied):
            store.assert_scope_current(principal, scope)


def test_store_failure_has_no_permissive_fallback(tmp_path):
    store = CorpusAccessStore(tmp_path / "access.sqlite")
    store.register_corpus(manifest(1), actor=admin())
    store.connection.close()
    with pytest.raises(CorpusAccessUnavailable):
        store.resolve_scope(user(1), "public-cti")


def test_cli_registers_only_from_admin_authored_manifest(tmp_path):
    access_path = tmp_path / "access.sqlite"
    config = tmp_path / "config.yaml"
    grant = tmp_path / "grant.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "access_store_path": str(access_path),
                "administrator": {
                    "principal_namespace": "local-admin",
                    "principal_id": "operator",
                    "capabilities": ["corpus:register"],
                },
            }
        ),
        encoding="utf-8",
    )
    grant.write_text(
        yaml.safe_dump(manifest(7).model_dump(mode="json")),
        encoding="utf-8",
    )
    register_corpus(config, grant)
    with CorpusAccessStore(access_path) as store:
        assert store.resolve_scope(user(7), "public-cti").scope_id == "scope-a"
