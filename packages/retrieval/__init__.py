"""Pure retrieval contracts and lazy advanced channel implementations."""
from .candidate import BackendHit, Candidate, Channel, ChannelResult, ChunkCandidate, ObjectCandidate, PathCandidate

__all__ = [
    "BackendHit",
    "Candidate",
    "Channel",
    "ChannelResult",
    "ChunkCandidate",
    "ExactIndex",
    "LexicalIndex",
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
    raise AttributeError(name)
