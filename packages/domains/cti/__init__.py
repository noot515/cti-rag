"""CTI domain semantics over generic evidence mechanics."""

from .adapter import CtiDomainAdapter
from .identifiers import normalize_identifier, normalize_observable, parse_cti_identifiers
from .normalize import load_cti_corpus_fixture, normalize_cti_fixture_manifest
from .schema import CtiChunk, CtiNormalizedEvidenceBatch, CtiObject, CtiQuarantinedRecord, CtiRelationship

__all__ = [
    "CtiChunk",
    "CtiDomainAdapter",
    "CtiNormalizedEvidenceBatch",
    "CtiObject",
    "CtiQuarantinedRecord",
    "CtiRelationship",
    "load_cti_corpus_fixture",
    "normalize_cti_fixture_manifest",
    "normalize_identifier",
    "normalize_observable",
    "parse_cti_identifiers",
]
