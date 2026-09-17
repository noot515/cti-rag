"""Trusted identity and corpus grant dependencies for the advanced API.

Importing this module is intentionally inert: the legacy SQLAlchemy/MySQL manager is
not imported until the FastAPI dependency factory is explicitly constructed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from packages.evidence.access import (
    CorpusAccessDenied,
    CorpusAccessStore,
    CorpusAccessUnavailable,
)
from packages.evidence.policy import ResolvedScope, TrustedPrincipal


class AdvancedIdentityError(PermissionError):
    pass


class AdvancedAccessHTTPError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class AdvancedAccessContext:
    principal: TrustedPrincipal
    scope: ResolvedScope


def trusted_principal_from_user(
    user: Any,
    *,
    capabilities: Iterable[str] = (),
) -> TrustedPrincipal:
    """Use canonical authenticated User.id; never the legacy/login User.user_id."""
    canonical_id = getattr(user, "id", None)
    if canonical_id is None:
        raise AdvancedIdentityError("authenticated-user-required")
    if getattr(user, "is_active", True) is False:
        raise AdvancedIdentityError("authenticated-user-disabled")
    return TrustedPrincipal(
        principal_id=str(canonical_id),
        principal_namespace="user.id",
        source="authenticated_api",
        capabilities=frozenset(str(item) for item in capabilities),
    )


def resolve_advanced_access(
    *,
    user: Any,
    corpus_key: str,
    access_store: CorpusAccessStore,
    capabilities: Iterable[str] = (),
) -> AdvancedAccessContext:
    principal = trusted_principal_from_user(user, capabilities=capabilities)
    scope = access_store.resolve_scope(principal, corpus_key)
    return AdvancedAccessContext(principal=principal, scope=scope)


def resolve_advanced_access_http(
    *,
    user: Any,
    corpus_key: str,
    access_store: CorpusAccessStore,
    capabilities: Iterable[str] = (),
) -> AdvancedAccessContext:
    try:
        return resolve_advanced_access(
            user=user,
            corpus_key=corpus_key,
            access_store=access_store,
            capabilities=capabilities,
        )
    except AdvancedIdentityError as exc:
        raise AdvancedAccessHTTPError(401, "invalid credentials") from exc
    except CorpusAccessDenied as exc:
        raise AdvancedAccessHTTPError(403, "corpus access denied") from exc
    except CorpusAccessUnavailable as exc:
        raise AdvancedAccessHTTPError(
            503,
            "advanced authorization unavailable",
        ) from exc


def make_advanced_access_dependency(
    access_store_provider: Callable[[], CorpusAccessStore],
    *,
    capability_resolver: Callable[[Any], Iterable[str]] | None = None,
):
    """Construct protected FastAPI integration and fail startup if signing is unsafe."""
    from fastapi import Depends, HTTPException
    from rag.utils.auth_utils import AuthUtils

    AuthUtils.configure_advanced_signing()
    from rag.utils.auth_middleware import get_required_user

    resolve_capabilities = capability_resolver or (lambda _user: ())

    async def dependency(
        corpus_key: str,
        user: Any = Depends(get_required_user),
    ) -> AdvancedAccessContext:
        try:
            return resolve_advanced_access_http(
                user=user,
                corpus_key=corpus_key,
                access_store=access_store_provider(),
                capabilities=resolve_capabilities(user),
            )
        except AdvancedAccessHTTPError as exc:
            headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.detail,
                headers=headers,
            ) from exc

    return dependency


__all__ = [
    "AdvancedAccessContext",
    "AdvancedAccessHTTPError",
    "AdvancedIdentityError",
    "make_advanced_access_dependency",
    "resolve_advanced_access",
    "resolve_advanced_access_http",
    "trusted_principal_from_user",
]
