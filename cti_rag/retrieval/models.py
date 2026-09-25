"""Persistent exact/lexical projection records."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional,Tuple
from cti_rag.contracts import AccessLabel,ensure_utc

@dataclass(frozen=True)
class LexicalDocument:
    passage_uid:str
    revision_uid:str
    object_uid:str
    namespace:str
    object_type:str
    canonical_id:str
    domain:str
    source_id:str
    tenant_id:str
    access_label:AccessLabel
    available_at:Optional[datetime]
    valid_from:Optional[datetime]
    valid_to:Optional[datetime]
    locator_json:str
    original_text:str
    normalized_text:str
    context_prefix:str
    analyzer_version:str
    def __post_init__(self):
        required=(self.passage_uid,self.revision_uid,self.object_uid,self.domain,self.source_id,self.tenant_id,self.locator_json,self.original_text,self.analyzer_version)
        if not all(v.strip() for v in required): raise ValueError("lexical document required fields missing")
        for value in (self.available_at,self.valid_from,self.valid_to):
            if value is not None: ensure_utc(value)

@dataclass(frozen=True)
class ExactRecord:
    revision_uid:str
    object_uid:str
    namespace:str
    object_type:str
    canonical_id:str
    domain:str
    source_id:str
    tenant_id:str
    access_label:AccessLabel
    available_at:Optional[datetime]
    valid_from:Optional[datetime]
    valid_to:Optional[datetime]
    locator_json:str
    original_text:str
    def __post_init__(self):
        required=(self.revision_uid,self.object_uid,self.namespace,self.object_type,self.canonical_id,self.domain,self.source_id,self.tenant_id,self.locator_json)
        if not all(v.strip() for v in required): raise ValueError("exact record required fields missing")
        for value in (self.available_at,self.valid_from,self.valid_to):
            if value is not None: ensure_utc(value)

class ExactLookupStatus(str,Enum):
    FOUND="found"; NOT_FOUND="not_found"; INVALID="invalid"; AMBIGUOUS="ambiguous"; REJECTED="rejected"

@dataclass(frozen=True)
class ExactLookupRequest:
    raw_identifier:str
    scope:object
    temporal:object
    snapshot:object
    namespace:Optional[str]=None
    object_type:Optional[str]=None
    valid_at:Optional[datetime]=None
    def __post_init__(self):
        if not self.raw_identifier.strip(): raise ValueError("raw_identifier required")
        if self.valid_at is not None: ensure_utc(self.valid_at)

@dataclass(frozen=True)
class ExactLookupResult:
    status:ExactLookupStatus
    records:Tuple[ExactRecord,...]=()
    reason:Optional[str]=None
