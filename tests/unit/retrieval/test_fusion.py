from __future__ import annotations

import math
import pytest

from packages.evidence.ids import canonical_hash
from packages.evidence.schema import (
    AuthorizedEvidenceView,
    ChannelScore,
    EvidencePolicyMetadata,
    ObjectCandidate,
    SnapshotRef,
)
from packages.retrieval.candidate import ChannelResult
from packages.retrieval.fusion import FusionError, fuse_channel_results
from packages.retrieval.planner import PlannerBounds, QueryPlan


def _snapshot():
    return SnapshotRef(
        domain="cti",
        scope_id="public",
        snapshot_id="g",
        manifest_sha256="1" * 64,
    )


def _candidate(
    channel: str,
    rank: int,
    revision: str,
    object_uid: str,
    raw=1.0,
):
    return ObjectCandidate(
        candidate_id=canonical_hash(["input", channel, rank, revision]),
        domain="cti",
        scope_id="public",
        snapshot=_snapshot(),
        target_object_uid=object_uid,
        authorized_view=AuthorizedEvidenceView(
            evidence_uid=revision,
            domain="cti",
            scope_id="public",
            source_instances=("fixture",),
            policy=EvidencePolicyMetadata(),
        ),
        channel_scores=(
            ChannelScore(
                channel=channel,
                rank=rank,
                raw_score=raw,
                score_kind="test",
            ),
        ),
        object_uid=object_uid,
    )


def _plan(task="general"):
    return QueryPlan(
        original_query="q",
        normalized_query="q",
        language="en",
        task=task,
        bounds=PlannerBounds(),
        exact_enabled=True,
        lexical_enabled=True,
        dense_enabled=True,
    )


def test_hand_computed_rrf_and_merge():
    revision = "2" * 64
    object_uid = "3" * 64
    exact = _candidate("exact", 1, revision, object_uid)
    lexical = _candidate("lexical", 2, revision, object_uid)
    other = _candidate("dense", 1, "4" * 64, "5" * 64)
    outcome = fuse_channel_results(
        (
            ChannelResult(channel="exact", status="ok", candidates=(exact,)),
            ChannelResult(channel="lexical", status="ok", candidates=(lexical,)),
            ChannelResult(channel="dense", status="ok", candidates=(other,)),
        ),
        plan=_plan(),
    )
    merged = next(
        candidate
        for candidate in outcome.candidates
        if candidate.object_uid == object_uid
    )
    assert math.isclose(merged.fused_score, 1 / 61 + 1 / 62)
    assert [score.channel for score in merged.channel_scores] == [
        "exact",
        "lexical",
    ]


def test_duplicate_candidate_within_channel_is_rejected():
    candidate = _candidate("dense", 1, "6" * 64, "7" * 64)
    with pytest.raises(FusionError, match="duplicate candidate"):
        fuse_channel_results(
            (
                ChannelResult(
                    channel="dense",
                    status="ok",
                    candidates=(candidate, candidate),
                ),
            ),
            plan=_plan(),
        )


def test_missing_channel_contributes_zero_and_stable_tie_break():
    lexical = _candidate("lexical", 1, "8" * 64, "9" * 64)
    dense = _candidate("dense", 1, "a" * 64, "b" * 64)
    outcome = fuse_channel_results(
        (
            ChannelResult(channel="lexical", status="ok", candidates=(lexical,)),
            ChannelResult(channel="dense", status="ok", candidates=(dense,)),
        ),
        plan=_plan(),
    )
    assert outcome.candidates[0].fused_score == outcome.candidates[1].fused_score
    assert [candidate.candidate_id for candidate in outcome.candidates] == sorted(
        candidate.candidate_id for candidate in outcome.candidates
    )


def test_exact_priority_reserved_only_for_entity_lookup():
    exact = _candidate("exact", 20, "c" * 64, "d" * 64)
    dense = _candidate("dense", 1, "e" * 64, "f" * 64)
    results = (
        ChannelResult(channel="exact", status="ok", candidates=(exact,)),
        ChannelResult(channel="dense", status="ok", candidates=(dense,)),
    )
    lookup = fuse_channel_results(results, plan=_plan("entity_lookup"))
    assert lookup.candidates[0].object_uid == "d" * 64
    mapping = fuse_channel_results(results, plan=_plan("mapping"))
    assert mapping.candidates[0].object_uid == "f" * 64


def test_nonfinite_score_rejected_by_candidate_contract():
    with pytest.raises(Exception):
        _candidate("dense", 1, "1" * 64, "2" * 64, raw=float("inf"))


def test_same_identity_with_inconsistent_evidence_payload_is_rejected():
    revision = "1" * 64
    first = _candidate("lexical", 1, revision, "2" * 64)
    second = _candidate("dense", 1, revision, "3" * 64)
    with pytest.raises(FusionError, match="inconsistent evidence"):
        fuse_channel_results(
            (
                ChannelResult(
                    channel="lexical",
                    status="ok",
                    candidates=(first,),
                ),
                ChannelResult(
                    channel="dense",
                    status="ok",
                    candidates=(second,),
                ),
            ),
            plan=_plan(),
        )
