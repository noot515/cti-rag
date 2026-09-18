"""External CTIConnect benchmark integration kept outside application runtime."""

from .adapter import (
    PINNED_COMMIT,
    CTIConnectAuditError,
    CTIConnectUnavailable,
    audit_external_root,
    load_corpus,
    load_queries_and_labels,
    official_identifier_score,
    run_cticonnect_retrieval_experiment,
)

__all__ = [
    "PINNED_COMMIT", "CTIConnectAuditError", "CTIConnectUnavailable",
    "audit_external_root", "load_corpus", "load_queries_and_labels",
    "official_identifier_score", "run_cticonnect_retrieval_experiment",
]
