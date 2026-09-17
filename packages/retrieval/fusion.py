"""Deterministic reciprocal-rank fusion for authorized retrieval candidates."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping

from packages.evidence.ids import canonical_hash
from packages.evidence.schema import Candidate, ChunkCandidate, ObjectCandidate, PathCandidate
from packages.retrieval.candidate import ChannelResult, TargetObjectRef, TargetProjection
from packages.retrieval.planner import QueryPlan, deduplicate_target_objects


class FusionError(ValueError):
    pass


def candidate_identity(candidate: Candidate) -> tuple[str, str]:
    """Identity is evidence kind plus immutable revision/reference identity."""
    if isinstance(candidate, ObjectCandidate):
        return ("object", candidate.authorized_view.evidence_uid)
    if isinstance(candidate, ChunkCandidate):
        return ("chunk", candidate.chunk_uid)
    if isinstance(candidate, PathCandidate):
        return ("path", candidate.path_id)
    raise TypeError(type(candidate))


def _validate_channel_result(result: ChannelResult) -> None:
    seen_identity: set[tuple[str, str]] = set()
    seen_rank: set[int] = set()
    for candidate in result.candidates:
        identity = candidate_identity(candidate)
        if identity in seen_identity:
            raise FusionError(f"duplicate candidate in channel {result.channel}")
        seen_identity.add(identity)
        own = tuple(
            score
            for score in candidate.channel_scores
            if score.channel == result.channel
        )
        if len(own) != 1 or len(candidate.channel_scores) != 1:
            raise FusionError(
                "each channel candidate must contain exactly one contribution from that channel"
            )
        score = own[0]
        if score.rank in seen_rank:
            raise FusionError(f"duplicate rank in channel {result.channel}")
        seen_rank.add(score.rank)
        if score.raw_score is not None and not math.isfinite(score.raw_score):
            raise FusionError("channel raw scores must be finite when present")


def _merge_signature(candidate: Candidate) -> dict:
    """Compare all evidence semantics while ignoring channel-local ranking fields."""
    payload = candidate.model_dump(mode="json")
    payload.pop("candidate_id", None)
    payload.pop("channel_scores", None)
    payload.pop("fused_score", None)
    payload.pop("rerank_score", None)
    return payload


def _same_evidence(left: Candidate, right: Candidate) -> bool:
    return type(left) is type(right) and _merge_signature(left) == _merge_signature(right)


def _is_exact_priority(candidate: Candidate, plan: QueryPlan) -> bool:
    return plan.task == "entity_lookup" and any(
        score.channel == "exact" for score in candidate.channel_scores
    )


@dataclass(frozen=True)
class FusionOutcome:
    candidates: tuple[Candidate, ...]
    target_order: tuple[TargetObjectRef, ...] = ()
    exact_priority_candidate_ids: tuple[str, ...] = ()


def fuse_channel_results(
    results: Iterable[ChannelResult],
    *,
    plan: QueryPlan,
    k: int = 60,
    weights: Mapping[str, float] | None = None,
    limit: int = 60,
    target_projections: Iterable[TargetProjection] = (),
) -> FusionOutcome:
    """Equal-weight RRF with deterministic evidence identity and stable tie breaks."""
    if k < 1 or limit < 1:
        raise FusionError("RRF k and fusion limit must be positive")
    weights = dict(weights or {})
    grouped: dict[tuple[str, str], tuple[Candidate, list]] = {}
    for result in results:
        _validate_channel_result(result)
        weight = float(weights.get(result.channel, 1.0))
        if not math.isfinite(weight) or weight < 0.0:
            raise FusionError("channel weights must be finite and non-negative")
        for candidate in result.candidates:
            identity = candidate_identity(candidate)
            existing = grouped.get(identity)
            contribution = candidate.channel_scores[0]
            if existing is None:
                grouped[identity] = (candidate, [contribution])
            else:
                base, contributions = existing
                if not _same_evidence(base, candidate):
                    raise FusionError(
                        "identical fusion identity maps to inconsistent evidence"
                    )
                if any(
                    item.channel == contribution.channel
                    for item in contributions
                ):
                    raise FusionError(
                        "candidate received more than one contribution from the same channel"
                    )
                contributions.append(contribution)

    fused: list[Candidate] = []
    for identity, (base, contributions) in grouped.items():
        contributions.sort(
            key=lambda score: (score.channel, score.rank, score.score_kind)
        )
        score = 0.0
        for contribution in contributions:
            weight = float(weights.get(contribution.channel, 1.0))
            score += weight / (k + contribution.rank)
        fused_id = canonical_hash(
            ["fused-candidate-v1", identity[0], identity[1]]
        )
        fused.append(
            base.model_copy(
                update={
                    "candidate_id": fused_id,
                    "channel_scores": tuple(contributions),
                    "fused_score": score,
                    "rerank_score": None,
                }
            )
        )

    fused.sort(
        key=lambda candidate: (
            0 if _is_exact_priority(candidate, plan) else 1,
            -(candidate.fused_score or 0.0),
            candidate.candidate_id,
        )
    )
    fused = fused[:limit]
    priority = tuple(
        candidate.candidate_id
        for candidate in fused
        if _is_exact_priority(candidate, plan)
    )
    target_order = deduplicate_target_objects(target_projections)
    return FusionOutcome(
        candidates=tuple(fused),
        target_order=target_order,
        exact_priority_candidate_ids=priority,
    )


__all__ = [
    "FusionError",
    "FusionOutcome",
    "candidate_identity",
    "fuse_channel_results",
]
