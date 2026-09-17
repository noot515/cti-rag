from __future__ import annotations

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
from packages.retrieval.citations import CitationRef
from packages.retrieval.context_packer import (
    ContextPacker,
    FixtureGeneratorTokenizer,
    PackingBudget,
    ResolvedEvidenceBlock,
)
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


class Handle:
    snapshot = SnapshotRef(
        domain="cti",
        scope_id="s",
        snapshot_id="g",
        manifest_sha256="1" * 64,
    )
    manifest = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Snapshots:
    def pin_active(self, scope):
        return Handle()


def candidate():
    uid = "2" * 64
    rev = "3" * 64
    return ObjectCandidate(
        candidate_id=canonical_hash(["e2e"]),
        domain="cti",
        scope_id="s",
        snapshot=Handle.snapshot,
        target_object_uid=uid,
        authorized_view=AuthorizedEvidenceView(
            evidence_uid=rev,
            domain="cti",
            scope_id="s",
            source_instances=("fixture",),
            policy=EvidencePolicyMetadata(),
        ),
        channel_scores=(
            ChannelScore(
                channel="lexical",
                rank=1,
                raw_score=1.0,
                score_kind="test",
            ),
        ),
        object_uid=uid,
    )


class Channel:
    name = "lexical"

    def search(self, plan, scope, snapshot, deadline):
        return ChannelResult(
            channel="lexical",
            status="ok",
            candidates=(candidate(),),
        )


class Resolver:
    def resolve(self, candidate, *, scope, snapshot, destination):
        return ResolvedEvidenceBlock(
            candidate_id=candidate.candidate_id,
            evidence_kind="object",
            evidence_uid=candidate.authorized_view.evidence_uid,
            object_uid=candidate.object_uid,
            body="CVE evidence text",
            citations=(
                CitationRef(
                    evidence_uid=candidate.authorized_view.evidence_uid,
                    evidence_kind="object",
                    domain="cti",
                    scope_id="s",
                    snapshot_id="g",
                    object_revision_uid=candidate.authorized_view.evidence_uid,
                    source_uri="fixture://object",
                ),
            ),
            source_keys=("fixture",),
            revision_uids=(candidate.authorized_view.evidence_uid,),
        )


def test_orchestrator_terminal_packing_emits_resolvable_citation():
    packer = ContextPacker(
        resolver=Resolver(),
        tokenizer=FixtureGeneratorTokenizer(),
        budget=PackingBudget(
            model_window=128,
            output_reserve_tokens=8,
            safety_margin_tokens=8,
        ),
    )
    orchestrator = AdvancedRetrievalOrchestrator(
        policy=Policy(),
        snapshot_manager=Snapshots(),
        planner=DeterministicQueryPlanner(Adapter()),
        channels={"lexical": Channel()},
        context_packer=packer,
    )
    try:
        result = orchestrator.retrieve(
            RetrievalRequest(query="what evidence", corpus_id="c", top_k=5),
            Principal(principal_id="u", source="trusted_local_cli"),
        )
    finally:
        orchestrator.close()
    assert "CVE evidence text" in result.answer_context
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert (
        result.answer_context[citation.emitted_start:citation.emitted_end]
        == "CVE evidence text"
    )
