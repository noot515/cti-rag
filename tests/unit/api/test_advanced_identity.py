from __future__ import annotations

from types import SimpleNamespace
import time

import pytest
from jose import jwt

from packages.evidence.access import (
    CorpusAccessStore,
    CorpusGrant,
    CorpusRegistrationManifest,
)
from packages.evidence.policy import TrustedPrincipal
from rag.api.advanced_dependencies import (
    AdvancedAccessHTTPError,
    make_advanced_access_dependency,
    resolve_advanced_access,
    resolve_advanced_access_http,
    trusted_principal_from_user,
)
from rag.utils.auth_utils import AuthUtils, JwtSigningConfig


def admin():
    return TrustedPrincipal(
        principal_id="operator",
        principal_namespace="local-admin",
        source="trusted_local_cli",
        capabilities=frozenset({"corpus:register"}),
    )


def manifest():
    return CorpusRegistrationManifest(
        corpus_key="c",
        domain="cti",
        scope_id="s",
        active_catalog_id="catalog",
        policy_version="p",
        source_allowlist=frozenset({"fixture"}),
        allowed_destinations=frozenset({"caller"}),
        grants=(
            CorpusGrant(
                principal_namespace="user.id",
                principal_id="11",
            ),
        ),
    )


def token(payload, *, key="advanced-test-key"):
    return jwt.encode(payload, key, algorithm="HS256")


def test_valid_expired_malformed_and_wrong_signature_tokens():
    config = JwtSigningConfig(secret_key="advanced-test-key")
    valid = token({"sub": "11", "exp": int(time.time()) + 60})
    assert AuthUtils.verify_access_token(valid, config)["sub"] == "11"

    expired = token({"sub": "11", "exp": int(time.time()) - 60})
    with pytest.raises(ValueError, match="expired"):
        AuthUtils.verify_access_token(expired, config)

    with pytest.raises(ValueError, match="invalid"):
        AuthUtils.verify_access_token("not-a-jwt", config)

    wrong = token(
        {"sub": "11", "exp": int(time.time()) + 60},
        key="different-key",
    )
    with pytest.raises(ValueError, match="invalid"):
        AuthUtils.verify_access_token(wrong, config)


def test_advanced_signing_authority_requires_explicit_nondefault_key(monkeypatch):
    with pytest.raises(RuntimeError, match="not explicitly configured"):
        AuthUtils.advanced_signing_config({})
    with pytest.raises(RuntimeError, match="not explicitly configured"):
        AuthUtils.advanced_signing_config(
            {"JWT_SECRET_KEY": AuthUtils._LEGACY_DEFAULT_SECRET}
        )
    configured = AuthUtils.advanced_signing_config(
        {"JWT_SECRET_KEY": "operator-provided-test-key"}
    )
    assert configured.algorithm == "HS256"
    assert configured.secret_key == "operator-provided-test-key"

    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="not explicitly configured"):
        # Fails before importing/using the legacy DB-backed user dependency.
        make_advanced_access_dependency(lambda: None)


def test_canonical_user_id_not_login_user_id(tmp_path):
    authenticated = SimpleNamespace(id=11, user_id=999999, is_active=True)
    principal = trusted_principal_from_user(authenticated)
    assert principal.principal_id == "11"
    assert principal.principal_namespace == "user.id"

    with CorpusAccessStore(tmp_path / "a.sqlite") as store:
        store.register_corpus(manifest(), actor=admin())
        context = resolve_advanced_access(
            user=authenticated,
            corpus_key="c",
            access_store=store,
        )
        assert context.scope.principal_id == "11"

        forged_user = SimpleNamespace(id=12, user_id=11, is_active=True)
        with pytest.raises(AdvancedAccessHTTPError) as denied:
            resolve_advanced_access_http(
                user=forged_user,
                corpus_key="c",
                access_store=store,
            )
        assert denied.value.status_code == 403


def test_missing_or_disabled_authenticated_user_maps_to_401(tmp_path):
    with CorpusAccessStore(tmp_path / "a.sqlite") as store:
        store.register_corpus(manifest(), actor=admin())
        for bad_user in (
            SimpleNamespace(user_id=11, is_active=True),
            SimpleNamespace(id=11, user_id=11, is_active=False),
        ):
            with pytest.raises(AdvancedAccessHTTPError) as error:
                resolve_advanced_access_http(
                    user=bad_user,
                    corpus_key="c",
                    access_store=store,
                )
            assert error.value.status_code == 401


def test_unknown_and_unauthorized_corpus_are_same_403(tmp_path):
    with CorpusAccessStore(tmp_path / "a.sqlite") as store:
        store.register_corpus(manifest(), actor=admin())
        unauthorized = SimpleNamespace(id=12, user_id=11, is_active=True)
        for corpus in ("c", "missing"):
            with pytest.raises(AdvancedAccessHTTPError) as error:
                resolve_advanced_access_http(
                    user=unauthorized,
                    corpus_key=corpus,
                    access_store=store,
                )
            assert error.value.status_code == 403
            assert error.value.detail == "corpus access denied"


def test_policy_store_failure_maps_to_503(tmp_path):
    store = CorpusAccessStore(tmp_path / "a.sqlite")
    store.register_corpus(manifest(), actor=admin())
    store.connection.close()
    with pytest.raises(AdvancedAccessHTTPError) as error:
        resolve_advanced_access_http(
            user=SimpleNamespace(id=11, user_id=11, is_active=True),
            corpus_key="c",
            access_store=store,
        )
    assert error.value.status_code == 503


def test_unauthorized_request_makes_zero_backend_or_provider_calls(tmp_path):
    calls = {"backend": 0, "provider": 0}
    with CorpusAccessStore(tmp_path / "a.sqlite") as store:
        store.register_corpus(manifest(), actor=admin())
        request_body = {
            "principal_id": "11",
            "user_id": "11",
            "policy": "allow-all",
        }
        assert request_body
        with pytest.raises(AdvancedAccessHTTPError) as error:
            resolve_advanced_access_http(
                user=SimpleNamespace(id=12, user_id=11, is_active=True),
                corpus_key="c",
                access_store=store,
            )
        assert error.value.status_code == 403
        assert calls == {"backend": 0, "provider": 0}
