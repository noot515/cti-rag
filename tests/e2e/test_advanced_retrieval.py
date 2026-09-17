from __future__ import annotations

from dataclasses import dataclass

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
from packages.retrieval.orchestrator import AdvancedRetrievalOrchestrator
from packages.retrieval.planner import DeterministicQueryPlanner


class Adapter:
    domain = "cti"

    def parse_identifiers(self, query):
        return []

    def allowed_graph_patterns(self, hint):
        return []

    def infer_task_hint(self, query, identifiers):
        return "general"

    def requested_target_types(self, query, identifiers, task):
        return ()


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


class FakeChannel:
    def __init__(self, name, result):
        self.name = name
        self.result = result

    def search(self, plan, scope, snapshot, deadline):
        return self.result


def candidate(channel, revision, object_uid):
    snapshot = Snapshots().pin_active(None).snapshot
    return ObjectCandidate(
        candidate_id=canonical_hash([channel, revision]),
        domain="cti",
        scope_id="s",
        snapshot=snapshot,
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
                rank=1,
                raw_score=1.0,
                score_kind="mechanics",
            ),
        ),
        object_uid=object_uid,
    )


def test_r1_to_r5_orchestration_configurations_execute_without_models_or_web():
    principal = Principal(
        principal_id="fixture",
        source="trusted_local_cli",
    )
    request = RetrievalRequest(
        query="general evidence",
        corpus_id="fixture",
        top_k=10,
    )

    def empty(name):
        return FakeChannel(
            name,
            ChannelResult(channel=name, status="no_results"),
        )

    configs = [
        {
            "lexical": FakeChannel(
                "lexical",
                ChannelResult(
                    channel="lexical",
                    status="ok",
                    candidates=(
                        candidate("lexical", "1" * 64, "2" * 64),
                    ),
                ),
            )
        },
        {
            "dense": FakeChannel(
                "dense",
                ChannelResult(
                    channel="dense",
                    status="ok",
                    candidates=(
                        candidate("dense", "3" * 64, "4" * 64),
                    ),
                ),
            )
        },
        {
            "lexical": empty("lexical"),
            "dense": empty("dense"),
        },
        {
            "exact": empty("exact"),
            "lexical": empty("lexical"),
            "dense": empty("dense"),
            "graph": empty("graph"),
        },
        {
            "lexical": FakeChannel(
                "lexical",
                ChannelResult(
                    channel="lexical",
                    status="ok",
                    candidates=(
                        candidate("lexical", "5" * 64, "6" * 64),
                    ),
                ),
            ),
            "dense": FakeChannel(
                "dense",
                ChannelResult(
                    channel="dense",
                    status="ok",
                    candidates=(
                        candidate("dense", "5" * 64, "6" * 64),
                    ),
                ),
            ),
        },
    ]

    for channels in configs:
        result = AdvancedRetrievalOrchestrator(
            policy=Policy(),
            snapshot_manager=Snapshots(),
            planner=DeterministicQueryPlanner(Adapter()),
            channels=channels,
        ).retrieve(request, principal)
        assert result.status in {"ok", "no_evidence", "partial"}
        assert all("text=" not in item for item in result.authorized_trace)
