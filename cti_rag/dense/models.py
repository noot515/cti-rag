"""Versioned dense-retrieval contracts with explicit embedding-space identity."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple
from cti_rag.contracts import AccessLabel, PolicyLabels, ensure_utc, sha256_hex

class PoolingMode(str, Enum):
    CLS="cls"; MEAN="mean"; LAST_TOKEN="last_token"; MODEL_DEFAULT="model_default"

class VectorNormalization(str, Enum):
    NONE="none"; L2="l2"

class DistanceMetric(str, Enum):
    COSINE="cosine"; INNER_PRODUCT="inner_product"; L2="l2"

@dataclass(frozen=True)
class EmbeddingFingerprint:
    provider: str
    model_name: str
    model_revision: str
    tokenizer_name: str
    tokenizer_revision: str
    dimension: int
    pooling: PoolingMode
    normalization: VectorNormalization
    distance_metric: DistanceMetric
    prefix_name: str = "deterministic-context"
    prefix_revision: str = "1"
    schema_version: str = "embedding-fingerprint/1"
    def __post_init__(self):
        fields=(self.provider,self.model_name,self.model_revision,self.tokenizer_name,self.tokenizer_revision,self.prefix_name,self.prefix_revision)
        if not all(v.strip() for v in fields): raise ValueError("embedding fingerprint fields must be non-empty")
        if self.dimension <= 0: raise ValueError("embedding dimension must be positive")
    @property
    def fingerprint_id(self):
        return sha256_hex({
            "schema":self.schema_version,"provider":self.provider,"model":self.model_name,"model_revision":self.model_revision,
            "tokenizer":self.tokenizer_name,"tokenizer_revision":self.tokenizer_revision,"dimension":self.dimension,
            "pooling":self.pooling.value,"normalization":self.normalization.value,"distance_metric":self.distance_metric.value,
            "prefix_name":self.prefix_name,"prefix_revision":self.prefix_revision,
        })
    @property
    def short_id(self): return self.fingerprint_id[:16]

@dataclass(frozen=True)
class EmbeddingInput:
    passage_uid: str
    revision_uid: str
    text: str
    prefix_text: str
    labels: PolicyLabels
    def __post_init__(self):
        if not self.passage_uid.strip() or not self.revision_uid.strip() or not self.text.strip(): raise ValueError("embedding input fields required")
    @property
    def model_text(self):
        return self.text if not self.prefix_text.strip() else f"{self.prefix_text.strip()}\n\n{self.text}"

@dataclass(frozen=True)
class DenseDocument:
    passage_uid: str
    revision_uid: str
    object_uid: str
    domain: str
    source_id: str
    tenant_id: str
    access_label: AccessLabel
    available_at: Optional[datetime]
    valid_from: Optional[datetime]
    valid_to: Optional[datetime]
    locator_json: str
    original_text: str
    context_prefix: str
    labels: PolicyLabels
    def __post_init__(self):
        required=(self.passage_uid,self.revision_uid,self.object_uid,self.domain,self.source_id,self.tenant_id,self.locator_json,self.original_text)
        if not all(v.strip() for v in required): raise ValueError("dense document required fields missing")
        for value in (self.available_at,self.valid_from,self.valid_to):
            if value is not None: ensure_utc(value)
        if self.labels.tenant_id != self.tenant_id: raise ValueError("dense document label tenant mismatch")
        if self.labels.access_label != self.access_label: raise ValueError("dense document access label mismatch")
    def embedding_input(self):
        return EmbeddingInput(self.passage_uid,self.revision_uid,self.original_text,self.context_prefix,self.labels)

@dataclass(frozen=True)
class DenseVectorRecord:
    passage_uid: str
    revision_uid: str
    object_uid: str
    domain: str
    source_id: str
    tenant_id: str
    access_label: AccessLabel
    available_at: Optional[datetime]
    valid_from: Optional[datetime]
    valid_to: Optional[datetime]
    locator_json: str
    original_text: str
    vector: Tuple[float,...]
    representation_uid: str
    embedding_fingerprint_id: str
    def __post_init__(self):
        if not self.vector: raise ValueError("dense vector cannot be empty")
        if not self.representation_uid.strip() or not self.embedding_fingerprint_id.strip(): raise ValueError("dense representation identity required")
        for value in (self.available_at,self.valid_from,self.valid_to):
            if value is not None: ensure_utc(value)

@dataclass(frozen=True)
class AnnRecallMeasurement:
    filter_name: str
    k: int
    eligible_count: int
    ann_ids: Tuple[str,...]
    exhaustive_ids: Tuple[str,...]
    recall: float
    def __post_init__(self):
        if self.k <= 0: raise ValueError("k must be positive")
        if not 0.0 <= self.recall <= 1.0: raise ValueError("recall must be in [0,1]")
