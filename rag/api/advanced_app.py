"""Isolated advanced FastAPI application factory.

This module intentionally does not import the legacy router package or construct
MySQL, Redis, RabbitMQ, GPU, Milvus, or Neo4j clients at import time.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from fastapi import FastAPI

from packages.evidence.access import CorpusAccessStore
from packages.evidence.config import AdvancedRagConfig
from rag.api.advanced_dependencies import AdvancedAccessContext
from rag.api.routers.advanced_retrieval_api import (
    AdvancedApiRuntime,
    create_advanced_router,
)


def create_advanced_app(
    *,
    config: AdvancedRagConfig,
    runtime_provider: Callable[[AdvancedAccessContext], AdvancedApiRuntime],
    access_store_provider: Callable[[], CorpusAccessStore],
    authenticated_user_dependency: Callable[..., Any] | None = None,
    capability_resolver: Callable[[Any], Iterable[str]] | None = None,
) -> FastAPI:
    """Build a direct advanced-only application.

    The documented direct route is `/chat/advanced-retrieval`. Deployments may add
    an outer proxy prefix, but the application itself does not secretly mount one.
    """
    app = FastAPI(title="CTI-RAG Advanced Retrieval", docs_url=None, redoc_url=None)
    app.include_router(
        create_advanced_router(
            config=config,
            runtime_provider=runtime_provider,
            access_store_provider=access_store_provider,
            authenticated_user_dependency=authenticated_user_dependency,
            capability_resolver=capability_resolver,
        )
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "advanced": "enabled" if config.enabled else "disabled"}

    return app


def create_fixture_app(
    *,
    config: AdvancedRagConfig,
    runtime_provider: Callable[[AdvancedAccessContext], AdvancedApiRuntime],
    access_store_provider: Callable[[], CorpusAccessStore],
    authenticated_user_dependency: Callable[..., Any],
    capability_resolver: Callable[[Any], Iterable[str]] | None = None,
) -> FastAPI:
    """Build the no-service fixture application using only injected local runtime pieces."""
    if config.profile != "fixture":
        raise ValueError("fixture app requires the fixture advanced profile")
    if config.network.allow_outbound or config.network.allow_downloads or config.network.web_search:
        raise ValueError("fixture app requires network-disabled configuration")
    if config.milvus.enabled:
        raise ValueError("fixture app cannot use the services Milvus backend")
    return create_advanced_app(
        config=config,
        runtime_provider=runtime_provider,
        access_store_provider=access_store_provider,
        authenticated_user_dependency=authenticated_user_dependency,
        capability_resolver=capability_resolver,
    )


__all__ = ["create_advanced_app", "create_fixture_app"]
