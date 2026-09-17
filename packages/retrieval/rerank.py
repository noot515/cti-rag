"""Single final reranking stage with explicit provider provenance and fail-closed egress."""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable, Literal, Protocol, Sequence

from pydantic import Field, StrictInt, field_validator, model_validator

from packages.evidence.policy import (
    ResolvedScope,
    authorize_evidence_set,
    require_authorized,
)
from packages.evidence.schema import (
    AuthorizedEvidenceView,
    Candidate,
    EvidenceModel,
    SnapshotRef,
)


RerankStatus = Literal["ok", "unavailable", "timeout", "error"]


class RerankError(RuntimeError):
    pass


class RerankValidationError(RerankError):
    pass


class RerankProviderError(RerankError):
    pass


class RerankProviderUnavailable(RerankProviderError):
    pass


class RequiredRerankerUnavailable(RerankError):
    pass


class RerankPayloadTooLarge(RerankError):
    pass


class IndexedRerankScore(EvidenceModel):
    index: StrictInt = Field(ge=0)
    score: float

    @field_validator("score")
    @classmethod
    def finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("rerank score must be finite")
        return value


class RerankResult(EvidenceModel):
    status: RerankStatus
    model_fingerprint: str = Field(min_length=1)
    scores_by_candidate_id: dict[str, float] = Field(default_factory=dict)
    reason: str | None = None

    @field_validator("scores_by_candidate_id")
    @classmethod
    def finite_scores(cls, values: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(float(value)) for value in values.values()):
            raise ValueError("rerank scores must be finite")
        return values

    @model_validator(mode="after")
    def status_shape(self):
        if self.status == "ok":
            if self.reason is not None:
                raise ValueError(
                    "successful rerank result must not contain failure reason"
                )
        else:
            if not self.reason:
                raise ValueError(
                    "failed rerank result requires explicit reason"
                )
            if self.scores_by_candidate_id:
                raise ValueError(
                    "failed rerank result must not contain scores"
                )
        return self


class RerankDocument(EvidenceModel):
    candidate_id: str = Field(min_length=1)
    text: str


class RerankProvider(Protocol):
    @property
    def fingerprint(self) -> str: ...

    def rerank(
        self,
        query: str,
        documents: Sequence[RerankDocument],
        *,
        deadline: float,
    ) -> RerankResult: ...


class RerankEgressGuard(Protocol):
    """Trusted boundary that reauthorizes query and complete candidate evidence.

    Implementations for PathCandidate must authorize every node revision, assertion
    revision and support evidence item before returning any document text.
    """

    def authorize_query(
        self,
        query: str,
        scope: ResolvedScope,
        destination: str,
    ) -> None: ...

    def authorize_and_materialize(
        self,
        candidate: Candidate,
        scope: ResolvedScope,
        snapshot: SnapshotRef,
        destination: str,
    ) -> str: ...


class RerankEvidenceBundle(EvidenceModel):
    """Provider document plus every evidence component that authorizes that text."""

    text: str
    views: tuple[AuthorizedEvidenceView, ...]


class RerankEvidenceResolver(Protocol):
    def resolve(
        self,
        candidate: Candidate,
        scope: ResolvedScope,
        snapshot: SnapshotRef,
    ) -> RerankEvidenceBundle: ...


class StrictRerankEgressGuard:
    """Concrete all-components authorization gate before reranker payload creation."""

    def __init__(self, *, policy, resolver: RerankEvidenceResolver) -> None:
        self.policy = policy
        self.resolver = resolver

    def authorize_query(
        self,
        query: str,
        scope: ResolvedScope,
        destination: str,
    ) -> None:
        if destination not in scope.allowed_destinations:
            raise PermissionError(
                "reranker destination is not authorized for query egress"
            )

    def authorize_and_materialize(
        self,
        candidate: Candidate,
        scope: ResolvedScope,
        snapshot: SnapshotRef,
        destination: str,
    ) -> str:
        bundle = self.resolver.resolve(candidate, scope, snapshot)
        # A path resolver must return node, assertion and support views; an empty
        # bundle fails closed through authorize_evidence_set.
        require_authorized(
            authorize_evidence_set(
                self.policy,
                bundle.views,
                scope,
                destination,
            )
        )
        return bundle.text


class RerankPayloadContract(EvidenceModel):
    tokenizer: Literal["unicode-codepoint-v1"] = "unicode-codepoint-v1"
    truncation: Literal["head-v1"] = "head-v1"
    max_query_codepoints: int = Field(default=8192, ge=1, le=8192)
    max_document_codepoints: int = Field(default=12000, ge=1)
    max_total_document_codepoints: int = Field(default=720000, ge=1)
    max_candidates: int = Field(default=60, ge=1, le=60)


def validate_indexed_rerank_response(
    candidate_ids: Sequence[str],
    indexed_scores: Sequence[IndexedRerankScore],
    *,
    model_fingerprint: str,
) -> RerankResult:
    """Map provider index output to IDs only after exhaustive index validation."""
    expected_count = len(candidate_ids)
    if len(indexed_scores) != expected_count:
        raise RerankValidationError(
            "rerank provider result count is incomplete"
        )
    seen: set[int] = set()
    scores: dict[str, float] = {}
    for item in indexed_scores:
        index = item.index
        if index in seen:
            raise RerankValidationError(
                "rerank provider returned duplicate index"
            )
        if index < 0 or index >= expected_count:
            raise RerankValidationError(
                "rerank provider returned out-of-range index"
            )
        if not math.isfinite(item.score):
            raise RerankValidationError(
                "rerank provider returned non-finite score"
            )
        seen.add(index)
        scores[candidate_ids[index]] = float(item.score)
    if seen != set(range(expected_count)):
        raise RerankValidationError(
            "rerank provider indices are not exhaustive"
        )
    return RerankResult(
        status="ok",
        model_fingerprint=model_fingerprint,
        scores_by_candidate_id=scores,
    )


def validate_complete_rerank_result(
    result: RerankResult,
    candidate_ids: Sequence[str],
    *,
    expected_fingerprint: str,
) -> RerankResult:
    if result.model_fingerprint != expected_fingerprint:
        raise RerankValidationError(
            "rerank model fingerprint mismatch"
        )
    if result.status != "ok":
        return result
    expected = tuple(candidate_ids)
    observed = tuple(result.scores_by_candidate_id)
    if len(observed) != len(expected) or set(observed) != set(expected):
        raise RerankValidationError(
            "successful rerank result must cover every requested candidate exactly once"
        )
    if any(
        not math.isfinite(float(value))
        for value in result.scores_by_candidate_id.values()
    ):
        raise RerankValidationError(
            "successful rerank result contains non-finite score"
        )
    return result


@dataclass(frozen=True)
class RerankOutcome:
    status: Literal["ok", "unavailable", "not_run"]
    candidates: tuple[Candidate, ...]
    model_fingerprint: str | None = None
    reason: str | None = None
    tail_candidate_ids: tuple[str, ...] = ()


class SingleFinalReranker:
    """Runs at most one logical provider call after fusion and before top-k truncation."""

    def __init__(
        self,
        *,
        provider: RerankProvider,
        egress_guard: RerankEgressGuard,
        required: bool = False,
        destination: str = "reranker_provider",
        stage_timeout_seconds: float = 4.0,
        payload_contract: RerankPayloadContract | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if stage_timeout_seconds <= 0:
            raise ValueError(
                "rerank stage timeout must be positive"
            )
        self.provider = provider
        self.egress_guard = egress_guard
        self.required = required
        self.destination = destination
        self.stage_timeout_seconds = stage_timeout_seconds
        self.payload_contract = (
            payload_contract or RerankPayloadContract()
        )
        self.clock = clock

    def _unavailable(
        self,
        candidates: tuple[Candidate, ...],
        *,
        reason: str,
        tail_candidate_ids: tuple[str, ...],
    ) -> RerankOutcome:
        if self.required:
            raise RequiredRerankerUnavailable(reason)
        return RerankOutcome(
            status="unavailable",
            candidates=candidates,
            model_fingerprint=self.provider.fingerprint,
            reason=reason,
            tail_candidate_ids=tail_candidate_ids,
        )

    def rerank(
        self,
        query: str,
        candidates: Sequence[Candidate],
        *,
        scope: ResolvedScope,
        snapshot: SnapshotRef,
        exact_priority_candidate_ids: Sequence[str] = (),
        request_deadline: float,
    ) -> RerankOutcome:
        original = tuple(candidates)
        if not original:
            return RerankOutcome(
                status="not_run",
                candidates=(),
            )
        head = original[: self.payload_contract.max_candidates]
        tail = original[self.payload_contract.max_candidates :]
        tail_ids = tuple(
            candidate.candidate_id for candidate in tail
        )
        deadline = min(
            request_deadline,
            self.clock() + self.stage_timeout_seconds,
        )
        if self.clock() >= deadline:
            return self._unavailable(
                original,
                reason="timeout",
                tail_candidate_ids=tail_ids,
            )

        # Query and all evidence are reauthorized immediately before any
        # provider call. No provider payload exists until this loop completes.
        self.egress_guard.authorize_query(
            query,
            scope,
            self.destination,
        )
        documents: list[RerankDocument] = []
        total_codepoints = 0
        for candidate in head:
            if self.clock() >= deadline:
                return self._unavailable(
                    original,
                    reason="timeout",
                    tail_candidate_ids=tail_ids,
                )
            text = self.egress_guard.authorize_and_materialize(
                candidate,
                scope,
                snapshot,
                self.destination,
            )
            truncated = text[
                : self.payload_contract.max_document_codepoints
            ]
            total_codepoints += len(truncated)
            if (
                total_codepoints
                > self.payload_contract.max_total_document_codepoints
            ):
                return self._unavailable(
                    original,
                    reason="payload-too-large",
                    tail_candidate_ids=tail_ids,
                )
            documents.append(
                RerankDocument(
                    candidate_id=candidate.candidate_id,
                    text=truncated,
                )
            )

        query_payload = query[
            : self.payload_contract.max_query_codepoints
        ]
        try:
            result = self.provider.rerank(
                query_payload,
                tuple(documents),
                deadline=deadline,
            )
        except TimeoutError:
            return self._unavailable(
                original,
                reason="timeout",
                tail_candidate_ids=tail_ids,
            )
        except RerankProviderError:
            return self._unavailable(
                original,
                reason="provider-error",
                tail_candidate_ids=tail_ids,
            )

        try:
            result = validate_complete_rerank_result(
                result,
                [candidate.candidate_id for candidate in head],
                expected_fingerprint=self.provider.fingerprint,
            )
        except RerankValidationError:
            return self._unavailable(
                original,
                reason="invalid-response",
                tail_candidate_ids=tail_ids,
            )
        if result.status != "ok":
            return self._unavailable(
                original,
                reason=result.status,
                tail_candidate_ids=tail_ids,
            )

        priority = frozenset(exact_priority_candidate_ids)
        prior_rank = {
            candidate.candidate_id: index
            for index, candidate in enumerate(head)
        }
        scored = [
            candidate.model_copy(
                update={
                    "rerank_score": result.scores_by_candidate_id[
                        candidate.candidate_id
                    ]
                }
            )
            for candidate in head
        ]
        scored.sort(
            key=lambda candidate: (
                0
                if candidate.candidate_id in priority
                else 1,
                -float(candidate.rerank_score),
                prior_rank[candidate.candidate_id],
            )
        )
        return RerankOutcome(
            status="ok",
            candidates=tuple(scored) + tail,
            model_fingerprint=result.model_fingerprint,
            tail_candidate_ids=tail_ids,
        )


__all__ = [
    "IndexedRerankScore",
    "RequiredRerankerUnavailable",
    "RerankDocument",
    "RerankEgressGuard",
    "RerankEvidenceBundle",
    "RerankEvidenceResolver",
    "RerankError",
    "RerankOutcome",
    "RerankPayloadContract",
    "RerankProvider",
    "RerankProviderError",
    "RerankProviderUnavailable",
    "RerankResult",
    "RerankValidationError",
    "SingleFinalReranker",
    "StrictRerankEgressGuard",
    "validate_complete_rerank_result",
    "validate_indexed_rerank_response",
]
