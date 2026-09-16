from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from packages.evidence.ids import canonical_hash, object_uid, path_uid, revision_uid
from packages.evidence.schema import (
    AuthorizedEvidenceView,
    Candidate,
    ChannelScore,
    EvidencePath,
    EvidencePolicyMetadata,
    ObjectCandidate,
    SnapshotRef,
)


def _snapshot(scope: str = "scope-a") -> SnapshotRef:
    return SnapshotRef(domain="cti", scope_id=scope, snapshot_id="snap-1", manifest_sha256="a" * 64)


def _view(scope: str = "scope-a") -> AuthorizedEvidenceView:
    return AuthorizedEvidenceView(evidence_uid="b" * 64, domain="cti", scope_id=scope,
                                  source_instances=("fixture-public",), policy=EvidencePolicyMetadata())


def test_candidate_discriminated_union_round_trip():
    uid = object_uid("cti", "fixture", "obj")
    candidate = ObjectCandidate(
        candidate_id="c" * 64,
        object_uid=uid,
        target_object_uid=uid,
        domain="cti",
        scope_id="scope-a",
        snapshot=_snapshot(),
        authorized_view=_view(),
        channel_scores=(ChannelScore(channel="exact", rank=1, raw_score=1.0, score_kind="exact"),),
    )
    adapter = TypeAdapter(Candidate)
    restored = adapter.validate_json(adapter.dump_json(candidate))
    assert restored == candidate
    assert restored.kind == "object"


def test_candidate_rejects_wrong_scope_and_duplicate_channel_contributions():
    uid = object_uid("cti", "fixture", "obj")
    with pytest.raises(ValidationError, match="authorized_view"):
        ObjectCandidate(candidate_id="c" * 64, object_uid=uid, domain="cti", scope_id="scope-a",
                        snapshot=_snapshot(), authorized_view=_view("scope-b"))
    with pytest.raises(ValidationError, match="duplicate channel"):
        ObjectCandidate(candidate_id="c" * 64, object_uid=uid, domain="cti", scope_id="scope-a",
                        snapshot=_snapshot(), authorized_view=_view(), channel_scores=(
                            ChannelScore(channel="dense", rank=1, raw_score=0.8, score_kind="cosine"),
                            ChannelScore(channel="dense", rank=2, raw_score=0.7, score_kind="cosine"),
                        ))


def test_candidate_rejects_nan_score():
    uid = object_uid("cti", "fixture", "obj")
    with pytest.raises(ValidationError):
        ObjectCandidate(candidate_id="c" * 64, object_uid=uid, domain="cti", scope_id="scope-a",
                        snapshot=_snapshot(), authorized_view=_view(), fused_score=float("nan"))


def test_evidence_path_records_pinned_node_revisions():
    a = object_uid("cti", "s", "a")
    b = object_uid("cti", "s", "b")
    ar = revision_uid(a, {"v": 1})
    br = revision_uid(b, {"v": 1})
    rr = canonical_hash(["relation-revision-v2", "r"])
    path = EvidencePath(
        path_id=path_uid([a, b], [rr], ["forward"]),
        domain="cti", scope_id="scope-a", snapshot=_snapshot(),
        ordered_node_uids=(a, b), ordered_node_revision_uids=(ar, br),
        ordered_relation_revision_uids=(rr,), traversal_directions=("forward",), domains_traversed=("cti",),
    )
    assert path.ordered_node_revision_uids == (ar, br)
