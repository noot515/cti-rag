from __future__ import annotations

import time

import pytest

from packages.evidence.ids import canonical_hash
from packages.evidence.policy import ResolvedScope
from packages.evidence.schema import (
    AuthorizedEvidenceView,
    ChannelScore,
    EvidencePolicyMetadata,
    ObjectCandidate,
    SnapshotRef,
)
from packages.retrieval.rerank import (
    IndexedRerankScore,
    RerankProviderError,
    RerankResult,
    SingleFinalReranker,
    validate_indexed_rerank_response,
)


def scope():
    return ResolvedScope(
        principal_id="u",
        corpus_id="c",
        domain="cti",
        scope_id="s",
        policy_version="p",
        source_allowlist=frozenset({"fixture"}),
        allowed_destinations=frozenset({"reranker_provider"}),
    )


def snapshot():
    return SnapshotRef(
        domain="cti",
        scope_id="s",
        snapshot_id="g",
        manifest_sha256="1" * 64,
    )


def candidate(index, exact=False):
    revision = f"{index + 1:064x}"[-64:]
    object_uid = f"{index + 101:064x}"[-64:]
    channel = "exact" if exact else "dense"
    return ObjectCandidate(
        candidate_id=canonical_hash(["c", index]),
        domain="cti",
        scope_id="s",
        snapshot=snapshot(),
        target_object_uid=object_uid,
        authorized_view=AuthorizedEvidenceView(
            evidence_uid=revision,
            domain="cti",
            scope_id="s",
            source_instances=("fixture",),
            policy=EvidencePolicyMetadata(),
        ),
        channel_scores=(
            ChannelScore(
                channel=channel,
                rank=index + 1,
                raw_score=1.0,
                score_kind="test",
            ),
        ),
        fused_score=1 / (61 + index),
        object_uid=object_uid,
    )


class Guard:
    def authorize_query(self, query, scope, destination):
        pass

    def authorize_and_materialize(
        self,
        candidate,
        scope,
        snapshot,
        destination,
    ):
        return f"doc {candidate.candidate_id}"


class Provider:
    fingerprint = "rerank-fixture-v1"

    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = 0

    def rerank(self, query, documents, *, deadline):
        self.calls += 1
        if self.exc:
            raise self.exc
        if self.result:
            return self.result
        return RerankResult(
            status="ok",
            model_fingerprint=self.fingerprint,
            scores_by_candidate_id={
                document.candidate_id: float(len(documents) - index)
                for index, document in enumerate(documents)
            },
        )


def test_reordered_valid_indices_map_to_candidate_ids():
    candidate_ids = ("a", "b", "c")
    result = validate_indexed_rerank_response(
        candidate_ids,
        (
            IndexedRerankScore(index=2, score=0.2),
            IndexedRerankScore(index=0, score=0.9),
            IndexedRerankScore(index=1, score=0.5),
        ),
        model_fingerprint="fp",
    )
    assert result.scores_by_candidate_id == {
        "c": 0.2,
        "a": 0.9,
        "b": 0.5,
    }


@pytest.mark.parametrize(
    "items",
    [
        (IndexedRerankScore(index=0, score=1.0),),
        (
            IndexedRerankScore(index=0, score=1.0),
            IndexedRerankScore(index=0, score=0.5),
        ),
        (
            IndexedRerankScore(index=0, score=1.0),
            IndexedRerankScore(index=2, score=0.5),
        ),
    ],
)
def test_missing_duplicate_and_out_of_range_indices_fail(items):
    with pytest.raises(Exception):
        validate_indexed_rerank_response(
            ("a", "b"),
            items,
            model_fingerprint="fp",
        )


def test_non_integer_and_nonfinite_raw_items_fail():
    with pytest.raises(Exception):
        IndexedRerankScore(index=0.0, score=1.0)
    with pytest.raises(Exception):
        IndexedRerankScore(index=0, score=float("nan"))
    with pytest.raises(Exception):
        IndexedRerankScore(index=0, score=float("inf"))


def test_empty_success_for_nonempty_batch_is_invalid_and_restores_order():
    candidates = (candidate(0), candidate(1))
    provider = Provider(
        RerankResult(
            status="ok",
            model_fingerprint="rerank-fixture-v1",
            scores_by_candidate_id={},
        )
    )
    outcome = SingleFinalReranker(
        provider=provider,
        egress_guard=Guard(),
    ).rerank(
        "q",
        candidates,
        scope=scope(),
        snapshot=snapshot(),
        request_deadline=time.monotonic() + 5,
    )
    assert outcome.status == "unavailable"
    assert outcome.candidates == candidates
    assert provider.calls == 1


def test_equal_scores_are_legitimate_and_keep_prior_rank():
    candidates = (candidate(0), candidate(1), candidate(2))
    provider = Provider(
        RerankResult(
            status="ok",
            model_fingerprint="rerank-fixture-v1",
            scores_by_candidate_id={
                item.candidate_id: 0.5 for item in candidates
            },
        )
    )
    outcome = SingleFinalReranker(
        provider=provider,
        egress_guard=Guard(),
    ).rerank(
        "q",
        candidates,
        scope=scope(),
        snapshot=snapshot(),
        request_deadline=time.monotonic() + 5,
    )
    assert outcome.status == "ok"
    assert [item.candidate_id for item in outcome.candidates] == [
        item.candidate_id for item in candidates
    ]


def test_provider_failure_and_timeout_restore_complete_order():
    candidates = (candidate(0), candidate(1), candidate(2))
    for exc in (RerankProviderError("down"), TimeoutError()):
        provider = Provider(exc=exc)
        outcome = SingleFinalReranker(
            provider=provider,
            egress_guard=Guard(),
        ).rerank(
            "q",
            candidates,
            scope=scope(),
            snapshot=snapshot(),
            request_deadline=time.monotonic() + 5,
        )
        assert outcome.status == "unavailable"
        assert outcome.candidates == candidates
        assert provider.calls == 1


def test_exact_priority_tier_survives_high_nonexact_rerank_score():
    exact = candidate(0, exact=True)
    other = candidate(1)
    provider = Provider(
        RerankResult(
            status="ok",
            model_fingerprint="rerank-fixture-v1",
            scores_by_candidate_id={
                exact.candidate_id: 0.0,
                other.candidate_id: 100.0,
            },
        )
    )
    outcome = SingleFinalReranker(
        provider=provider,
        egress_guard=Guard(),
    ).rerank(
        "q",
        (exact, other),
        scope=scope(),
        snapshot=snapshot(),
        exact_priority_candidate_ids=(exact.candidate_id,),
        request_deadline=time.monotonic() + 5,
    )
    assert outcome.candidates[0].candidate_id == exact.candidate_id


def test_tail_beyond_sixty_is_not_reranked_and_keeps_order():
    candidates = tuple(candidate(index) for index in range(62))
    provider = Provider()
    outcome = SingleFinalReranker(
        provider=provider,
        egress_guard=Guard(),
    ).rerank(
        "q",
        candidates,
        scope=scope(),
        snapshot=snapshot(),
        request_deadline=time.monotonic() + 5,
    )
    assert provider.calls == 1
    assert outcome.tail_candidate_ids == (
        candidates[60].candidate_id,
        candidates[61].candidate_id,
    )
    assert [item.candidate_id for item in outcome.candidates[-2:]] == [
        candidates[60].candidate_id,
        candidates[61].candidate_id,
    ]
