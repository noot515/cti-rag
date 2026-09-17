"""Pure retrieval contracts and lazy advanced channel implementations."""
from .candidate import (
    BackendHit,
    Candidate,
    Channel,
    ChannelResult,
    ChunkCandidate,
    ObjectCandidate,
    PathCandidate,
    TargetObjectRef,
    TargetProjection,
)

__all__ = [
    "AdvancedRetrievalOrchestrator",
    "BackendHit",
    "Candidate",
    "CatalogEvidenceResolver",
    "CatalogNeighborReader",
    "Channel",
    "ChannelResult",
    "ChunkCandidate",
    "CitationEntry",
    "CitationRef",
    "ContextPacker",
    "DeterministicQueryPlanner",
    "ExactIndex",
    "FixtureGeneratorTokenizer",
    "FusionOutcome",
    "GraphSearchEngine",
    "IndexedRerankScore",
    "LexicalIndex",
    "Neo4jNeighborReader",
    "ObjectCandidate",
    "PackResult",
    "PackingBudget",
    "PathCandidate",
    "QueryPlan",
    "RerankResult",
    "RetrievalUnavailable",
    "SingleFinalReranker",
    "StrictRerankEgressGuard",
    "TargetObjectRef",
    "TargetProjection",
    "fuse_channel_results",
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
    if name in {"DeterministicQueryPlanner", "QueryPlan"}:
        from .planner import DeterministicQueryPlanner, QueryPlan
        return {
            "DeterministicQueryPlanner": DeterministicQueryPlanner,
            "QueryPlan": QueryPlan,
        }[name]
    if name in {"FusionOutcome", "fuse_channel_results"}:
        from .fusion import FusionOutcome, fuse_channel_results
        return {
            "FusionOutcome": FusionOutcome,
            "fuse_channel_results": fuse_channel_results,
        }[name]
    if name in {"AdvancedRetrievalOrchestrator", "RetrievalUnavailable"}:
        from .orchestrator import AdvancedRetrievalOrchestrator, RetrievalUnavailable
        return {
            "AdvancedRetrievalOrchestrator": AdvancedRetrievalOrchestrator,
            "RetrievalUnavailable": RetrievalUnavailable,
        }[name]
    if name in {
        "IndexedRerankScore",
        "RerankResult",
        "SingleFinalReranker",
        "StrictRerankEgressGuard",
    }:
        from .rerank import (
            IndexedRerankScore,
            RerankResult,
            SingleFinalReranker,
            StrictRerankEgressGuard,
        )
        return {
            "IndexedRerankScore": IndexedRerankScore,
            "RerankResult": RerankResult,
            "SingleFinalReranker": SingleFinalReranker,
            "StrictRerankEgressGuard": StrictRerankEgressGuard,
        }[name]
    if name in {"CitationEntry", "CitationRef"}:
        from .citations import CitationEntry, CitationRef
        return {"CitationEntry": CitationEntry, "CitationRef": CitationRef}[name]
    if name in {
        "CatalogEvidenceResolver",
        "ContextPacker",
        "FixtureGeneratorTokenizer",
        "PackResult",
        "PackingBudget",
    }:
        from .context_packer import (
            CatalogEvidenceResolver,
            ContextPacker,
            FixtureGeneratorTokenizer,
            PackResult,
            PackingBudget,
        )
        return {
            "CatalogEvidenceResolver": CatalogEvidenceResolver,
            "ContextPacker": ContextPacker,
            "FixtureGeneratorTokenizer": FixtureGeneratorTokenizer,
            "PackResult": PackResult,
            "PackingBudget": PackingBudget,
        }[name]
    raise AttributeError(name)
