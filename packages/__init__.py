"""Top-level compatibility facade for ThreatRAG packages.

Importing this module is deliberately side-effect free. Legacy runtime objects are
constructed only when a caller explicitly asks for them.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from typing import Any

_runtime_lock = RLock()
_executor: ThreadPoolExecutor | None = None
_knowledge_base: Any = None
_graph_base: Any = None
_retriever: Any = None


def get_runtime_config():
    """Return the single legacy Config instance, creating it on first access."""
    from .config import get_runtime_config as _get_runtime_config

    return _get_runtime_config()


class _LegacyConfigProxy:
    """Lazy attribute proxy preserving ``from packages import config`` callers."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_runtime_config(), name)

    def __getitem__(self, key: str) -> Any:
        return get_runtime_config()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        get_runtime_config()[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return get_runtime_config().get(key, default)

    def __repr__(self) -> str:
        return "<lazy legacy Config proxy>"


# Python replaces this package attribute with the packages.config submodule if that
# submodule is imported explicitly. packages.config implements its own module-level
# __getattr__ proxy, so both import orders keep attribute-style compatibility.
config = _LegacyConfigProxy()


def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _runtime_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor()
    return _executor


def get_knowledge_base():
    global _knowledge_base
    if _knowledge_base is None:
        with _runtime_lock:
            if _knowledge_base is None:
                from packages.core import KnowledgeBase

                _knowledge_base = KnowledgeBase()
    return _knowledge_base


def get_graph_base():
    global _graph_base
    if _graph_base is None:
        with _runtime_lock:
            if _graph_base is None:
                from packages.core import GraphDatabase

                _graph_base = GraphDatabase()
    return _graph_base


def get_retriever():
    global _retriever
    if _retriever is None:
        with _runtime_lock:
            if _retriever is None:
                from packages.core.retriever import Retriever

                _retriever = Retriever()
    return _retriever


def __getattr__(name: str) -> Any:
    if name == "executor":
        return get_executor()
    if name == "knowledge_base":
        return get_knowledge_base()
    if name == "graph_base":
        return get_graph_base()
    if name == "retriever":
        return get_retriever()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "config",
    "executor",
    "knowledge_base",
    "graph_base",
    "retriever",
    "get_runtime_config",
    "get_executor",
    "get_knowledge_base",
    "get_graph_base",
    "get_retriever",
]
