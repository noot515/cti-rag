"""CTI domain semantics over generic evidence mechanics."""

from .adapter import CtiDomainAdapter
from .identifiers import normalize_identifier, parse_cti_identifiers
from .schema import CtiChunk, CtiNormalizedEvidenceBatch, CtiObject, CtiRelationship

__all__ = [
    "CtiChunk",
    "CtiDomainAdapter",
    "CtiNormalizedEvidenceBatch",
    "CtiObject",
    "CtiRelationship",
    "normalize_identifier",
    "parse_cti_identifiers",
]
