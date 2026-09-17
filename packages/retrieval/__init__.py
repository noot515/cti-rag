"""Pure retrieval contracts and lazy advanced channel implementations."""
from .candidate import BackendHit, Candidate, Channel, ChannelResult, ChunkCandidate, ObjectCandidate, PathCandidate

__all__ = [
    "BackendHit",
    "Candidate",
    "CatalogNeighborReader",
    "Channel",
    "ChannelResult",
    "ChunkCandidate",
    "ExactIndex",
    "GraphSearchEngine",
    "LexicalIndex",
    "Neo4jNeighborReader",
    "ObjectCandidate",
    "PathCandidate",
]


def __getattr__(name: str):
    if name == "ExactIndex":
        from .exact import ExactIndex
        return ExactIndex
    if name == "LexicalIndex":
        from .lexical import LexicalIndex
        return LexicalIndex
    if name in {"CatalogNeighborReader", "GraphSearchEngine", "Neo4jNeighborReader"}:
        from .graph import CatalogNeighborReader, GraphSearchEngine, Neo4jNeighborReader
        return {
            "CatalogNeighborReader": CatalogNeighborReader,
            "GraphSearchEngine": GraphSearchEngine,
            "Neo4jNeighborReader": Neo4jNeighborReader,
        }[name]
    raise AttributeError(name)
