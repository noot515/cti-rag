"""Router assembly helpers.

The package initializer intentionally avoids importing legacy routers eagerly so
`rag.api.routers.advanced_retrieval_api` can be imported in an isolated process.
"""
from __future__ import annotations

from fastapi import APIRouter


def build_legacy_router() -> APIRouter:
    from rag.api.routers.chat_api import chat
    from rag.api.routers.data_api import data
    from rag.api.routers.graph_api import graph
    from rag.api.routers.token_api import auth

    combined = APIRouter()
    combined.include_router(chat)
    combined.include_router(data)
    combined.include_router(graph)
    combined.include_router(auth)
    return combined


def __getattr__(name: str):
    # Preserve `from rag.api.routers import router` for legacy callers while
    # preventing advanced submodule imports from instantiating legacy runtime deps.
    if name == "router":
        return build_legacy_router()
    raise AttributeError(name)


__all__ = ["build_legacy_router", "router"]
