"""Pure contracts for the advanced evidence/RAG implementation."""
from .config import AdvancedRagConfig, AdvancedRagConfigError, RuntimeFactories, load_advanced_rag_config
from .domain import DomainAdapter, GraphPattern, NormalizedEvidenceBatch
from .ids import chunk_uid, object_uid, path_uid, physical_key, relation_revision_uid, relation_uid, revision_uid
from .migrations import MigrationError
from .policy import (
    AuthorizedScope,
    DenyByDefaultPolicy,
    PolicyDenied,
    Principal,
    PublicFixturePolicy,
    ResolvedScope,
    RetrievalPolicy,
    TrustedPrincipal,
    authorize_evidence_set,
)
from .raw_store import RawHashConflict, RawHashMismatch, RawPayloadStore, RawStoreError
from .schema import (
    Candidate,
    ChunkCandidate,
    EvidenceChunk,
    EvidenceObject,
    EvidencePath,
    EvidenceRelation,
    ExternalIdentifier,
    ObjectCandidate,
    PathCandidate,
    RetrievalCandidate,
    RetrievalRequest,
    RetrievalResult,
    SnapshotRef,
    SourceRef,
)
from .store import CheckpointUpdate, EvidenceStore, PersistResult

__all__ = [
    "AdvancedRagConfig", "AdvancedRagConfigError", "AuthorizedScope", "Candidate", "CheckpointUpdate",
    "ChunkCandidate", "DenyByDefaultPolicy", "DomainAdapter", "EvidenceChunk", "EvidenceObject",
    "EvidencePath", "EvidenceRelation", "EvidenceStore", "ExternalIdentifier", "GraphPattern", "MigrationError",
    "NormalizedEvidenceBatch", "ObjectCandidate", "PathCandidate", "PersistResult", "PolicyDenied", "Principal",
    "PublicFixturePolicy", "RawHashConflict", "RawHashMismatch", "RawPayloadStore", "RawStoreError", "ResolvedScope",
    "RetrievalCandidate", "RetrievalPolicy", "RetrievalRequest", "RetrievalResult", "RuntimeFactories", "SnapshotRef",
    "SourceRef", "TrustedPrincipal", "authorize_evidence_set", "chunk_uid", "load_advanced_rag_config", "object_uid",
    "path_uid", "physical_key", "relation_revision_uid", "relation_uid", "revision_uid",
]
