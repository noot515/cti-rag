"""Pure contracts for the advanced evidence/RAG implementation."""

from .config import AdvancedRagConfig, AdvancedRagConfigError, RuntimeFactories, load_advanced_rag_config
from .ids import chunk_uid, object_uid, path_uid, relation_revision_uid, relation_uid, revision_uid
from .policy import (
    DenyByDefaultPolicy,
    PolicyDenied,
    PublicFixturePolicy,
    RetrievalPolicy,
    TrustedPrincipal,
)
from .schema import (
    EvidenceChunk,
    EvidenceObject,
    EvidencePath,
    EvidenceRelation,
    ExternalIdentifier,
    RetrievalCandidate,
    RetrievalRequest,
    RetrievalResult,
    SourceRef,
)

__all__ = [
    "AdvancedRagConfig",
    "AdvancedRagConfigError",
    "DenyByDefaultPolicy",
    "EvidenceChunk",
    "EvidenceObject",
    "EvidencePath",
    "EvidenceRelation",
    "ExternalIdentifier",
    "PolicyDenied",
    "PublicFixturePolicy",
    "RetrievalCandidate",
    "RetrievalPolicy",
    "RetrievalRequest",
    "RetrievalResult",
    "RuntimeFactories",
    "SourceRef",
    "TrustedPrincipal",
    "chunk_uid",
    "load_advanced_rag_config",
    "object_uid",
    "path_uid",
    "relation_revision_uid",
    "relation_uid",
    "revision_uid",
]
