from __future__ import annotations

from dataclasses import dataclass
import time

import pytest

from packages.evidence.ids import canonical_hash
from packages.evidence.policy import Principal, ResolvedScope
from packages.evidence.schema import (
    AuthorizedEvidenceView,
    ChannelScore,
    EvidencePolicyMetadata,
    ObjectCandidate,
    RetrievalRequest,
    SnapshotRef,
)
from packages.retrieval.candidate import ChannelResult
from packages.retrieval.orchestrator import (
    AdvancedRetrievalOrchestrator,
    BoundedExecutor,
    ChannelBackendError,
    RetrievalUnavailable,
)
from packages.retrieval.planner import DeterministicQueryPlanner


class Adapter:
    domain = "cti"

    def parse_identifiers(self, query):
        from packages.evidence.schema import ExternalIdentifier

        if "CVE-" in query:
            return [
                ExternalIdentifier(
                    namespace="cve",
                    value="CVE-2026-999999",
                    domain="cti",
                )
            ]
        return []

    def allowed_graph_patterns(self, hint):
        from packages.evidence.domain import GraphPattern

        if hint in {"mapping", "three_hop_mapping"}:
            return [
                GraphPattern(
                    pattern_id="map",
                    relation_sequence=("maps_to",),
                    max_hops=2,
                )
            ]
        return []

    def infer_task_hint(self, query, identifiers):
        if "map" in query.lower():
            return "mapping"
        return "entity_lookup" if identifiers else "general"

    def requested_target_types(self, query, identifiers, task):
        return ("weakness",) if task == "mapping" else ()


class Policy:
    def resolve_scope(self, principal, corpus):
        return ResolvedScope(
            principal_id=principal.principal_id,
            corpus_id=corpus,
            domain="cti",
            scope_id="s",
            policy_version="p",
            source_allowlist=frozenset({"fixture"}),
            allowed_destinations=frozenset({"caller"}),
        )


@dataclass
class Handle:
    snapshot: SnapshotRef
    manifest: object = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Snapshots:
    def pin_active(self, scope):
        return Handle(
            SnapshotRef(
                domain="cti",
                scope_id="s",
                snapshot_id="g",
                manifest_sha256="1" * 64,
            )
        )


def candidate(channel, rank, revision, object_uid):
    return ObjectCandidate(
        candidate_id=canonical_hash([channel, revision]),
        domain="cti",
        scope_id="s",
        snapshot=Snapshots().pin_active(None).snapshot,
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
                rank=rank,
                raw_score=1.0,
                score_kind="test",
            ),
        ),
        object_uid=object_uid,
    )


class FakeChannel:
    def __init__(
        self,
        name,
        result=None,
        delay=0.0,
        raise_backend=False,
    ):
        self.name = name
        self.result = result
        self.delay = delay
        self.raise_backend = raise_backend

    def search(self, plan, scope, snapshot, deadline):
        if self.delay:
            time.sleep(self.delay)
        if self.raise_backend:
            raise ChannelBackendError("down")
        return self.result or ChannelResult(channel=self.name, status="no_results")


def make(channels, *, timeout=0.2, executor_factory=None):
    return AdvancedRetrievalOrchestrator(
        policy=Policy(),
        snapshot_manager=Snapshots(),
        planner=DeterministicQueryPlanner(Adapter()),
        channels=channels,
        total_timeout_seconds=1.0,
        channel_timeout_seconds=timeout,
        executor_factory=executor_factory,
    )


def test_independent_channels_fuse_and_repeat_stably():
    revision = "2" * 64
    object_uid = "3" * 64
    channels = {
        "lexical": FakeChannel(
            "lexical",
            ChannelResult(
                channel="lexical",
                status="ok",
                candidates=(candidate("lexical", 1, revision, object_uid),),
            ),
        ),
        "dense": FakeChannel(
            "dense",
            ChannelResult(
                channel="dense",
                status="ok",
                candidates=(candidate("dense", 1, revision, object_uid),),
            ),
        ),
    }
    request = RetrievalRequest(
        query="general question",
        corpus_id="fixture",
        top_k=10,
    )
    principal = Principal(principal_id="u", source="trusted_local_cli")
    first = make(channels).retrieve(request, principal)
    second = make(channels).retrieve(request, principal)
    assert first.status == "ok"
    assert len(first.candidates) == 1
    assert first.candidates[0].candidate_id == second.candidates[0].candidate_id
    assert {score.channel for score in first.candidates[0].channel_scores} == {
        "lexical",
        "dense",
    }


def test_backend_timeout_allows_successful_sibling_and_is_traced():
    good = ChannelResult(
        channel="lexical",
        status="ok",
        candidates=(candidate("lexical", 1, "4" * 64, "5" * 64),),
    )
    channels = {
        "lexical": FakeChannel("lexical", good),
        "dense": FakeChannel("dense", delay=0.05),
    }
    result = make(channels, timeout=0.01).retrieve(
        RetrievalRequest(query="general", corpus_id="fixture"),
        Principal(principal_id="u", source="trusted_local_cli"),
    )
    assert result.status == "partial"
    assert result.candidates
    assert any("status=timeout" in item for item in result.authorized_trace)


def test_successful_empty_is_distinct_from_failed():
    result = make({"lexical": FakeChannel("lexical")}).retrieve(
        RetrievalRequest(query="general", corpus_id="fixture"),
        Principal(principal_id="u", source="trusted_local_cli"),
    )
    assert result.status == "no_evidence"
    with pytest.raises(RetrievalUnavailable):
        make(
            {
                "lexical": FakeChannel(
                    "lexical",
                    raise_backend=True,
                )
            }
        ).retrieve(
            RetrievalRequest(query="general", corpus_id="fixture"),
            Principal(principal_id="u", source="trusted_local_cli"),
        )


def test_exact_seed_enables_graph_after_exact_only():
    exact = ChannelResult(
        channel="exact",
        status="ok",
        candidates=(candidate("exact", 1, "6" * 64, "7" * 64),),
    )
    channels = {
        "exact": FakeChannel("exact", exact),
        "graph": FakeChannel(
            "graph",
            ChannelResult(channel="graph", status="no_results"),
        ),
        "lexical": FakeChannel("lexical"),
        "dense": FakeChannel("dense"),
    }
    execution = make(channels).retrieve_candidates(
        RetrievalRequest(
            query="map CVE-2026-999999 to CWE",
            corpus_id="fixture",
        ),
        Principal(principal_id="u", source="trusted_local_cli"),
    )
    assert execution.plan.graph_enabled
    assert any(result.channel == "graph" for result in execution.channel_results)


def test_queue_saturation_is_bounded_and_explicit():
    factory = lambda: BoundedExecutor(max_workers=1, queue_capacity=0)
    channels = {
        "lexical": FakeChannel("lexical", delay=0.03),
        "dense": FakeChannel("dense", delay=0.03),
    }
    execution = make(
        channels,
        timeout=0.1,
        executor_factory=factory,
    ).retrieve_candidates(
        RetrievalRequest(query="general", corpus_id="fixture"),
        Principal(principal_id="u", source="trusted_local_cli"),
    )
    assert any(result.status == "error" for result in execution.channel_results)


def test_unexpected_policy_or_catalog_exception_is_fatal():
    class Fatal(FakeChannel):
        def search(self, *args, **kwargs):
            raise PermissionError("policy")

    with pytest.raises(PermissionError):
        make({"lexical": Fatal("lexical")}).retrieve(
            RetrievalRequest(query="general", corpus_id="fixture"),
            Principal(principal_id="u", source="trusted_local_cli"),
        )
