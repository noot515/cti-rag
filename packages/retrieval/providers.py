"""Fingerprint-bound embedding provider contracts for the advanced retrieval path.

Importing this module is intentionally inert: no provider SDK, model artifact, network
client, environment file, or legacy embedding implementation is imported or created.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import time
from typing import Callable, Iterable, Literal, Mapping, Protocol, Sequence

from pydantic import Field, field_validator, model_validator

from packages.evidence.ids import canonical_hash
from packages.evidence.schema import EvidenceModel
from packages.evidence.validation import require_sha256

EmbeddingMetric = Literal["cosine", "ip", "l2"]
EmbeddingNormalization = Literal["none", "l2"]
EgressDestination = Literal["local_generator", "embedding_provider"]


class EmbeddingProviderError(RuntimeError):
    pass


class EmbeddingProviderUnavailable(EmbeddingProviderError):
    pass


class EmbeddingValidationError(EmbeddingProviderError):
    pass


class EmbeddingFingerprintMismatch(EmbeddingProviderError):
    pass


class EmbeddingDeadlineExceeded(EmbeddingProviderError):
    pass


class EmbeddingCancelled(EmbeddingProviderError):
    pass


class EmbeddingEgressDenied(PermissionError, EmbeddingProviderError):
    pass


class EmbeddingFingerprint(EvidenceModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    dimensions: int = Field(ge=1)
    metric: EmbeddingMetric
    normalization: EmbeddingNormalization
    document_instruction: str
    query_instruction: str
    tokenizer: str = Field(min_length=1)
    artifact_sha256: str | None = None
    remote: bool = False

    @field_validator("artifact_sha256")
    @classmethod
    def validate_artifact_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_sha256(value, field_name="artifact_sha256")

    @property
    def digest(self) -> str:
        return canonical_hash(["embedding-fingerprint-v1", self.model_dump(mode="json")])

    @model_validator(mode="after")
    def explicit_reproducibility(self) -> "EmbeddingFingerprint":
        if not self.revision:
            raise ValueError("embedding revision must be explicit, including 'unavailable'")
        return self


class EmbeddingInput(EvidenceModel):
    item_id: str = Field(min_length=1)
    text: str


class IndexedEmbedding(EvidenceModel):
    item_id: str = Field(min_length=1)
    vector: tuple[float, ...]


class EmbeddingBatch(EvidenceModel):
    fingerprint: EmbeddingFingerprint
    embeddings: tuple[IndexedEmbedding, ...]


class EmbeddingProvider(Protocol):
    @property
    def fingerprint(self) -> EmbeddingFingerprint: ...

    def encode_documents(
        self,
        items: Sequence[EmbeddingInput],
        *,
        destination: EgressDestination,
        deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> EmbeddingBatch: ...

    def encode_queries(
        self,
        items: Sequence[EmbeddingInput],
        *,
        destination: EgressDestination,
        deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> EmbeddingBatch: ...


def _check_runtime(*, deadline: float | None, cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise EmbeddingCancelled("embedding request was cancelled")
    if deadline is not None and time.monotonic() >= deadline:
        raise EmbeddingDeadlineExceeded("embedding request deadline expired")


def _l2_norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def validate_embedding_batch(
    batch: EmbeddingBatch,
    *,
    expected_ids: Iterable[str],
    expected_fingerprint: EmbeddingFingerprint,
) -> EmbeddingBatch:
    if batch.fingerprint.digest != expected_fingerprint.digest:
        raise EmbeddingFingerprintMismatch(
            "embedding fingerprint mismatch; the generation must be reindexed"
        )
    expected = tuple(expected_ids)
    observed = tuple(item.item_id for item in batch.embeddings)
    if len(observed) != len(set(observed)):
        raise EmbeddingValidationError("embedding output contains duplicate item IDs")
    if set(observed) != set(expected) or len(observed) != len(expected):
        raise EmbeddingValidationError("embedding output does not map exactly to requested IDs")

    by_id = {item.item_id: item for item in batch.embeddings}
    ordered: list[IndexedEmbedding] = []
    for item_id in expected:
        item = by_id[item_id]
        vector = item.vector
        if len(vector) != expected_fingerprint.dimensions:
            raise EmbeddingValidationError(
                f"embedding dimension mismatch for {item_id}: "
                f"expected {expected_fingerprint.dimensions}, observed {len(vector)}"
            )
        if any(not math.isfinite(value) for value in vector):
            raise EmbeddingValidationError(f"embedding vector for {item_id} contains non-finite values")
        if expected_fingerprint.normalization == "l2":
            norm = _l2_norm(vector)
            if not math.isfinite(norm) or abs(norm - 1.0) > 1e-6:
                raise EmbeddingValidationError(
                    f"embedding vector for {item_id} is not L2 normalized"
                )
        ordered.append(item)
    return EmbeddingBatch(fingerprint=batch.fingerprint, embeddings=tuple(ordered))


class _ProviderBase:
    def __init__(
        self,
        fingerprint: EmbeddingFingerprint,
        *,
        allowed_destinations: frozenset[str],
    ) -> None:
        if not allowed_destinations:
            raise ValueError("embedding provider requires an explicit destination allowlist")
        self._fingerprint = fingerprint
        self._allowed_destinations = allowed_destinations

    @property
    def fingerprint(self) -> EmbeddingFingerprint:
        return self._fingerprint

    def _authorize_destination(self, destination: str) -> None:
        if destination not in self._allowed_destinations:
            raise EmbeddingEgressDenied("embedding destination is not authorized")

    def _before_call(
        self,
        *,
        destination: str,
        deadline: float | None,
        cancelled: Callable[[], bool] | None,
    ) -> None:
        self._authorize_destination(destination)
        _check_runtime(deadline=deadline, cancelled=cancelled)


class DeterministicFixtureEmbeddingProvider(_ProviderBase):
    """Stdlib-only deterministic embeddings for mechanics tests.

    The vectors are intentionally not semantic embeddings and must not be used to
    claim retrieval quality. They exist to exercise fingerprint, indexing, ranking,
    persistence, and policy boundaries without model downloads or network access.
    """

    def __init__(
        self,
        *,
        dimensions: int = 64,
        metric: EmbeddingMetric = "cosine",
        normalization: EmbeddingNormalization = "l2",
        revision: str = "v1",
        document_instruction: str = "fixture-document",
        query_instruction: str = "fixture-query",
        tokenizer: str = "utf8-bytes-sha256-v1",
        allowed_destinations: frozenset[str] = frozenset({"local_generator"}),
    ) -> None:
        fingerprint = EmbeddingFingerprint(
            provider="fixture",
            model="deterministic-hash-embedding",
            revision=revision,
            dimensions=dimensions,
            metric=metric,
            normalization=normalization,
            document_instruction=document_instruction,
            query_instruction=query_instruction,
            tokenizer=tokenizer,
            artifact_sha256=canonical_hash(
                ["deterministic-fixture-embedding-artifact-v1", dimensions, revision]
            ),
            remote=False,
        )
        super().__init__(fingerprint, allowed_destinations=allowed_destinations)

    def _vector(self, *, instruction: str, text: str) -> tuple[float, ...]:
        values: list[float] = []
        counter = 0
        seed = (instruction + "\x00" + text).encode("utf-8")
        while len(values) < self.fingerprint.dimensions:
            block = hashlib.sha256(seed + counter.to_bytes(8, "big")).digest()
            for offset in range(0, len(block), 4):
                integer = int.from_bytes(block[offset : offset + 4], "big")
                values.append((integer / 2147483647.5) - 1.0)
                if len(values) == self.fingerprint.dimensions:
                    break
            counter += 1
        if self.fingerprint.normalization == "l2":
            norm = _l2_norm(values)
            if norm == 0.0:
                raise EmbeddingValidationError("deterministic embedding unexpectedly has zero norm")
            values = [value / norm for value in values]
        return tuple(values)

    def _encode(
        self,
        items: Sequence[EmbeddingInput],
        *,
        instruction: str,
        destination: EgressDestination,
        deadline: float | None,
        cancelled: Callable[[], bool] | None,
    ) -> EmbeddingBatch:
        self._before_call(destination=destination, deadline=deadline, cancelled=cancelled)
        if len({item.item_id for item in items}) != len(items):
            raise EmbeddingValidationError("embedding request contains duplicate item IDs")
        output: list[IndexedEmbedding] = []
        for item in items:
            _check_runtime(deadline=deadline, cancelled=cancelled)
            output.append(
                IndexedEmbedding(
                    item_id=item.item_id,
                    vector=self._vector(instruction=instruction, text=item.text),
                )
            )
        return validate_embedding_batch(
            EmbeddingBatch(fingerprint=self.fingerprint, embeddings=tuple(output)),
            expected_ids=(item.item_id for item in items),
            expected_fingerprint=self.fingerprint,
        )

    def encode_documents(
        self,
        items: Sequence[EmbeddingInput],
        *,
        destination: EgressDestination,
        deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> EmbeddingBatch:
        return self._encode(
            items,
            instruction=self.fingerprint.document_instruction,
            destination=destination,
            deadline=deadline,
            cancelled=cancelled,
        )

    def encode_queries(
        self,
        items: Sequence[EmbeddingInput],
        *,
        destination: EgressDestination,
        deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> EmbeddingBatch:
        return self._encode(
            items,
            instruction=self.fingerprint.query_instruction,
            destination=destination,
            deadline=deadline,
            cancelled=cancelled,
        )


@dataclass(frozen=True)
class EmbeddingProviderSelection:
    provider: str
    fingerprint_digest: str


class EmbeddingProviderRegistry:
    """Trusted lazy provider selection with no implicit fallback."""

    def __init__(self, factories: Mapping[str, Callable[[], EmbeddingProvider]]) -> None:
        self._factories = dict(factories)

    def create(self, provider_name: str) -> EmbeddingProvider:
        factory = self._factories.get(provider_name)
        if factory is None:
            raise EmbeddingProviderUnavailable(
                f"selected embedding provider {provider_name!r} is unavailable"
            )
        provider = factory()
        if provider.fingerprint.provider != provider_name:
            raise EmbeddingValidationError("provider factory returned a mismatched provider identity")
        return provider


__all__ = [
    "DeterministicFixtureEmbeddingProvider",
    "EgressDestination",
    "EmbeddingBatch",
    "EmbeddingCancelled",
    "EmbeddingDeadlineExceeded",
    "EmbeddingEgressDenied",
    "EmbeddingFingerprint",
    "EmbeddingFingerprintMismatch",
    "EmbeddingInput",
    "EmbeddingMetric",
    "EmbeddingNormalization",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EmbeddingProviderRegistry",
    "EmbeddingProviderSelection",
    "EmbeddingProviderUnavailable",
    "EmbeddingValidationError",
    "IndexedEmbedding",
    "validate_embedding_batch",
]
