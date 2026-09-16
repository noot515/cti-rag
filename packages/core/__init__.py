"""Lazy compatibility exports for the legacy core package."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "HistoryManager": (".history", "HistoryManager"),
    "KnowledgeBase": (".knowledgebase", "KnowledgeBase"),
    "GraphDatabase": (".graphbase", "GraphDatabase"),
    "MilvusManager": ("..manager.milvus_manager", "MilvusManager"),
    "get_milvus_manager": ("..manager.milvus_manager", "get_milvus_manager"),
    "Neo4jManager": ("..manager.neo4j_manager", "Neo4jManager"),
    "get_neo4j_manager": ("..manager.neo4j_manager", "get_neo4j_manager"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, symbol_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name, __name__)
    value = getattr(module, symbol_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = list(_EXPORTS)
