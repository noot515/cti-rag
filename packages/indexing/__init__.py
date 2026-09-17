"""Advanced publication/indexing contracts with import-safe lazy implementations."""
from .manifests import GenerationManifest, GenerationMember, ProjectionReceipt, ProjectionSpec, ProjectionWriter

__all__ = [
    "ChunkingConfig",
    "DeterministicTokenizer",
    "ExactProjectionWriter",
    "GenerationManifest",
    "GenerationMember",
    "LexicalProjectionWriter",
    "ProjectionReceipt",
    "ProjectionSpec",
    "ProjectionWriter",
    "PublicationOrchestrator",
    "chunk_object",
    "chunk_objects",
]


def __getattr__(name: str):
    if name == "PublicationOrchestrator":
        from .orchestrator import PublicationOrchestrator
        return PublicationOrchestrator
    if name in {"ChunkingConfig", "DeterministicTokenizer", "chunk_object", "chunk_objects"}:
        from .chunker import ChunkingConfig, DeterministicTokenizer, chunk_object, chunk_objects
        return {
            "ChunkingConfig": ChunkingConfig,
            "DeterministicTokenizer": DeterministicTokenizer,
            "chunk_object": chunk_object,
            "chunk_objects": chunk_objects,
        }[name]
    if name in {"ExactProjectionWriter", "LexicalProjectionWriter"}:
        from .lexical_indexer import ExactProjectionWriter, LexicalProjectionWriter
        return {"ExactProjectionWriter": ExactProjectionWriter, "LexicalProjectionWriter": LexicalProjectionWriter}[name]
    raise AttributeError(name)
