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
    RerankEvidenceBundle,
    RerankResult,
    SingleFinalReranker,
    StrictRerankEgressGuard,
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


def cand(index):
    revision = f"{index + 1:064x}"[-64:]
    object_uid = f"{index + 100:064x}"[-64:]
    return ObjectCandidate(
        candidate_id=canonical_hash(["egress", index]),
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
                channel="dense",
                rank=index + 1,
                raw_score=1.0,
                score_kind="test",
            ),
        ),
        object_uid=object_uid,
    )


class Provider:
    fingerprint = "fp"

    def __init__(self):
        self.calls = []

    def rerank(self, query, documents, *, deadline):
        self.calls.append((query, tuple(document.text for document in documents)))
        return RerankResult(
            status="ok",
            model_fingerprint=self.fingerprint,
            scores_by_candidate_id={
                document.candidate_id: 1.0 for document in documents
            },
        )


class Guard:
    def __init__(self, deny_index=None):
        self.query_calls = 0
        self.materialized = []
        self.deny_index = deny_index

    def authorize_query(self, query, scope, destination):
        self.query_calls += 1

    def authorize_and_materialize(
        self,
        candidate,
        scope,
        snapshot,
        destination,
    ):
        index = len(self.materialized)
        if self.deny_index == index:
            raise PermissionError("revoked")
        text = f"authorized-{index}"
        self.materialized.append(text)
        return text


def test_query_and_all_evidence_reauthorized_immediately_before_single_call():
    provider = Provider()
    guard = Guard()
    candidates = (cand(0), cand(1))
    outcome = SingleFinalReranker(
        provider=provider,
        egress_guard=guard,
    ).rerank(
        "query",
        candidates,
        scope=scope(),
        snapshot=snapshot(),
        request_deadline=time.monotonic() + 5,
    )
    assert outcome.status == "ok"
    assert guard.query_calls == 1
    assert len(guard.materialized) == 2
    assert len(provider.calls) == 1
    assert provider.calls[0][1] == ("authorized-0", "authorized-1")


def test_revocation_between_retrieval_and_egress_sends_zero_provider_payload():
    provider = Provider()
    guard = Guard(deny_index=0)
    with pytest.raises(PermissionError):
        SingleFinalReranker(
            provider=provider,
            egress_guard=guard,
        ).rerank(
            "query",
            (cand(0),),
            scope=scope(),
            snapshot=snapshot(),
            request_deadline=time.monotonic() + 5,
        )
    assert provider.calls == []


def test_partial_materialization_then_denial_still_calls_provider_zero_times():
    provider = Provider()
    guard = Guard(deny_index=1)
    with pytest.raises(PermissionError):
        SingleFinalReranker(
            provider=provider,
            egress_guard=guard,
        ).rerank(
            "query",
            (cand(0), cand(1)),
            scope=scope(),
            snapshot=snapshot(),
            request_deadline=time.monotonic() + 5,
        )
    assert provider.calls == []


def test_document_and_query_payload_contract_is_deterministic():
    provider = Provider()
    guard = Guard()
    long_query = "q" * 9000
    outcome = SingleFinalReranker(
        provider=provider,
        egress_guard=guard,
    ).rerank(
        long_query,
        (cand(0),),
        scope=scope(),
        snapshot=snapshot(),
        request_deadline=time.monotonic() + 5,
    )
    assert outcome.status == "ok"
    assert len(provider.calls[0][0]) == 8192


def test_strict_guard_requires_all_resolved_support_views():
    class Decision:
        def __init__(self, allowed):
            self.allowed = allowed
            self.reason = "ok" if allowed else "denied"

    class Policy:
        def authorize_evidence(self, view, scope, destination):
            return Decision(view.evidence_uid != "f" * 64)

    class Resolver:
        def resolve(self, candidate, scope, snapshot):
            good = AuthorizedEvidenceView(
                evidence_uid="e" * 64,
                domain="cti",
                scope_id="s",
                source_instances=("fixture",),
                policy=EvidencePolicyMetadata(),
            )
            denied = AuthorizedEvidenceView(
                evidence_uid="f" * 64,
                domain="cti",
                scope_id="s",
                source_instances=("fixture",),
                policy=EvidencePolicyMetadata(),
            )
            return RerankEvidenceBundle(
                text="never-egressed",
                views=(good, denied),
            )

    provider = Provider()
    guard = StrictRerankEgressGuard(
        policy=Policy(),
        resolver=Resolver(),
    )
    with pytest.raises(PermissionError):
        SingleFinalReranker(
            provider=provider,
            egress_guard=guard,
        ).rerank(
            "query",
            (cand(0),),
            scope=scope(),
            snapshot=snapshot(),
            request_deadline=time.monotonic() + 5,
        )
    assert provider.calls == []
