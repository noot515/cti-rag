"""Authenticated advanced retrieval route factory.

Importing this module is inert: no legacy router, database manager, provider, or
backend is constructed until a caller explicitly builds an enabled router.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Protocol

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from packages.evidence.access import CorpusAccessStore, CorpusAccessUnavailable
from packages.evidence.config import AdvancedRagConfig
from packages.evidence.policy import PolicyDenied
from packages.evidence.schema import RetrievalRequest, RetrievalResult
from packages.retrieval.orchestrator import RetrievalUnavailable
from rag.api.advanced_dependencies import (
    AdvancedAccessContext,
    AdvancedAccessHTTPError,
    resolve_advanced_access_http,
)


class AdvancedRetrievalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    db_id: str = Field(min_length=1)
    top_k: int = Field(default=12, ge=1, le=50)
    max_graph_hops: int = Field(default=2, ge=0, le=3)
    response_mode: str = Field(default="summary", pattern="^(summary|full)$")
    web_search: StrictBool = False

    @field_validator("query")
    @classmethod
    def bound_query_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 8192:
            raise ValueError("query exceeds the 8192-byte advanced API limit")
        return value

    @model_validator(mode="after")
    def forbid_web_search(self) -> "AdvancedRetrievalBody":
        if self.web_search:
            raise ValueError("advanced retrieval does not permit web_search=true")
        return self


class AdvancedRetrievalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_run_id: str
    domain: str
    snapshot_id: str
    status: str
    answer_context: str
    citations: list[dict[str, Any]]
    candidates: list[dict[str, Any]] | None = None
    channel_status: dict[str, str]
    degraded_channels: list[str]
    truncated: bool
    timings: dict[str, float]
    model_fingerprints: dict[str, str]


class ResultFinalizer(Protocol):
    def __call__(
        self,
        result: RetrievalResult,
        context: AdvancedAccessContext,
    ) -> RetrievalResult: ...


class DebugCandidateAuthorizer(Protocol):
    def __call__(
        self,
        candidate: Any,
        context: AdvancedAccessContext,
    ) -> bool: ...


@dataclass(frozen=True)
class AdvancedApiRuntime:
    orchestrator: Any
    finalize_result: ResultFinalizer
    authorize_debug_candidate: DebugCandidateAuthorizer | None = None


def _channel_summary(trace: Iterable[str]) -> tuple[dict[str, str], list[str]]:
    states: dict[str, str] = {}
    degraded: list[str] = []
    for entry in trace:
        if not entry.startswith("channel="):
            continue
        values: dict[str, str] = {}
        for part in entry.split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                values[key] = value
        name = values.get("channel")
        channel_status = values.get("status")
        if not name or not channel_status:
            continue
        states[name] = channel_status
        if channel_status in {"timeout", "error"} or (
            channel_status == "not_run" and values.get("reason") != "plan-disabled"
        ):
            degraded.append(name)
    return states, sorted(set(degraded))


def _http_error(exc: AdvancedAccessHTTPError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail=exc.detail,
        headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None,
    )


def create_advanced_router(
    *,
    config: AdvancedRagConfig,
    runtime_provider: Callable[[AdvancedAccessContext], AdvancedApiRuntime],
    access_store_provider: Callable[[], CorpusAccessStore],
    authenticated_user_dependency: Callable[..., Any] | None = None,
    capability_resolver: Callable[[Any], Iterable[str]] | None = None,
) -> APIRouter:
    """Create the direct-app `/chat/advanced-retrieval` route.

    Disabled configuration returns an empty router.  If no authenticated-user
    dependency is injected, construction validates the advanced JWT authority and
    only then imports the legacy user lookup.  Fixture apps inject their identity
    dependency and therefore do not import MySQL/Redis/RabbitMQ runtime modules.
    """

    router = APIRouter()
    if not config.enabled:
        return router

    if authenticated_user_dependency is None:
        from rag.utils.auth_utils import AuthUtils

        AuthUtils.configure_advanced_signing()
        from rag.utils.auth_middleware import get_required_user

        authenticated_user_dependency = get_required_user

    resolve_capabilities = capability_resolver or (lambda _user: ())

    @router.post(
        "/chat/advanced-retrieval",
        response_model=AdvancedRetrievalResponse,
        response_model_exclude_none=True,
    )
    async def advanced_retrieval(
        body: AdvancedRetrievalBody,
        user: Any = Depends(authenticated_user_dependency),
    ) -> AdvancedRetrievalResponse:
        # Authentication and server-owned grant resolution happen before runtime
        # construction so an unauthorized request cannot reach a backend/provider.
        try:
            context = resolve_advanced_access_http(
                user=user,
                corpus_key=body.db_id,
                access_store=access_store_provider(),
                capabilities=frozenset(str(item) for item in resolve_capabilities(user)),
            )
        except AdvancedAccessHTTPError as exc:
            raise _http_error(exc) from exc

        if body.response_mode == "full" and "evidence:debug" not in context.principal.capabilities:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="evidence debug access denied",
            )

        request = RetrievalRequest(
            query=body.query,
            corpus_id=body.db_id,
            top_k=body.top_k,
            max_graph_hops=body.max_graph_hops,
            response_mode=body.response_mode,
        )
        try:
            runtime = runtime_provider(context)
            result = runtime.orchestrator.retrieve(request, context.principal)
            # The runtime must recheck current scope/evidence immediately before
            # serialization; Prompt 14 already rechecks packed evidence, and this
            # callback closes the remaining route-level withdrawal window.
            result = runtime.finalize_result(result, context)
        except RetrievalUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="advanced retrieval unavailable",
            ) from exc
        except CorpusAccessUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="advanced authorization unavailable",
            ) from exc
        except PolicyDenied as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="corpus access denied",
            ) from exc

        channel_status, degraded_channels = _channel_summary(result.authorized_trace)
        serialized_candidates: list[dict[str, Any]] | None = None
        if body.response_mode == "full":
            serialized_candidates = []
            authorizer = runtime.authorize_debug_candidate
            if authorizer is not None:
                for candidate in result.candidates:
                    if authorizer(candidate, context):
                        serialized_candidates.append(candidate.model_dump(mode="json"))

        return AdvancedRetrievalResponse(
            retrieval_run_id=result.retrieval_run_id,
            domain=result.domain,
            snapshot_id=result.snapshot.snapshot_id,
            status=result.status,
            answer_context=result.answer_context,
            citations=[item.model_dump(mode="json") for item in result.citations],
            candidates=serialized_candidates,
            channel_status=channel_status,
            degraded_channels=degraded_channels,
            truncated=result.truncated,
            timings=dict(result.timings_ms),
            model_fingerprints=dict(result.model_fingerprints),
        )

    return router


__all__ = [
    "AdvancedApiRuntime",
    "AdvancedRetrievalBody",
    "AdvancedRetrievalResponse",
    "create_advanced_router",
]
