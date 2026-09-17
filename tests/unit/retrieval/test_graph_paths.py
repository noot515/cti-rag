from __future__ import annotations

import time
import pytest

from packages.evidence.domain import GraphPattern
from packages.evidence.policy import PolicyDecision, ResolvedScope
from packages.evidence.schema import SnapshotRef
from packages.indexing.graph_indexer import CatalogGraphProjectionWriter
from packages.indexing.manifests import GenerationManifest, GenerationMember, ProjectionSpec
from packages.retrieval.graph import CatalogNeighborReader, GraphSearchEngine, UnknownGraphPattern


def h(ch: str) -> str:
    return ch * 64


class Store:
    def __init__(self):
        self.objects = {}
        self.relations = {}

    def get_revision(self, domain, scope_id, revision_uid):
        return self.objects.get(revision_uid)

    def get_assertion(self, domain, scope_id, revision_uid):
        return self.relations.get(revision_uid)


def obj(uid, rev, typ):
    return {
        "kind": "object",
        "evidence_uid": uid,
        "revision_uid": rev,
        "payload": {"object_type": typ, "name": uid[:3], "policy": {}},
        "sources": [{"raw_sha256": h("f"), "source_instance": "fixture", "source_object_id": uid}],
    }


def rel(uid, rev, src, tgt, relation="maps_to"):
    return {
        "relation_uid": uid,
        "revision_uid": rev,
        "payload": {
            "source_object_uid": src,
            "target_object_uid": tgt,
            "original_relation": relation,
            "normalized_relation": relation,
            "assertion_kind": "catalog_mapping",
            "direction": "forward",
            "qualifiers": [],
            "source_field_path": "x",
            "policy": {},
        },
        "sources": [{"raw_sha256": h("e"), "source_instance": "fixture", "source_object_id": uid}],
    }


class Policy:
    def __init__(self, deny=frozenset()):
        self.deny = deny

    def authorize_evidence(self, view, scope, destination):
        allowed = view.evidence_uid not in self.deny
        return PolicyDecision(allowed=allowed, reason="ok" if allowed else "deny")


def setup_graph(*, cycle=False, high_degree=0):
    store = Store()
    members = []
    nodes = [
        (h("a"), h("1"), "vulnerability"),
        (h("b"), h("2"), "weakness"),
        (h("c"), h("3"), "attack-pattern"),
        (h("d"), h("4"), "technique"),
    ]
    for uid, rev, typ in nodes:
        store.objects[rev] = obj(uid, rev, typ)
        members.append(GenerationMember(kind="object", evidence_uid=uid, revision_uid=rev))
    relations = [
        (h("e"), h("5"), h("a"), h("b")),
        (h("f"), h("6"), h("b"), h("c")),
        (h("7"), h("8"), h("c"), h("d")),
    ]
    if cycle:
        relations.append((h("0"), h("9"), h("c"), h("a")))
    for uid, rev, source, target in relations:
        store.relations[rev] = rel(uid, rev, source, target)
        members.append(GenerationMember(kind="relation", evidence_uid=uid, revision_uid=rev))
    for index in range(high_degree):
        uid = f"{index:064x}"[-64:]
        revision = f"{1000 + index:064x}"[-64:]
        relation_uid = f"{2000 + index:064x}"[-64:]
        relation_revision = f"{3000 + index:064x}"[-64:]
        store.objects[revision] = obj(uid, revision, "weakness")
        members.append(GenerationMember(kind="object", evidence_uid=uid, revision_uid=revision))
        store.relations[relation_revision] = rel(relation_uid, relation_revision, h("a"), uid)
        members.append(
            GenerationMember(kind="relation", evidence_uid=relation_uid, revision_uid=relation_revision)
        )
    writer = CatalogGraphProjectionWriter(store)
    manifest = GenerationManifest(
        generation_id=h("9"),
        domain="cti",
        scope_id="s",
        corpus_id="c",
        membership=tuple(sorted(members, key=lambda item: (item.kind, item.evidence_uid, item.revision_uid))),
        projections=(ProjectionSpec(backend="graph", enabled=True, required=True, fingerprint=writer.fingerprint),),
        fingerprints={},
    )
    return store, manifest


def run(store, manifest, pattern, *, seeds=(h("a"),), policy=None, max_hops=None, neighbor_limit=30):
    scope = ResolvedScope(
        principal_id="p",
        corpus_id="c",
        domain="cti",
        scope_id="s",
        policy_version="test",
        source_allowlist=frozenset({"fixture"}),
        allowed_destinations=frozenset({"caller"}),
    )
    snapshot = SnapshotRef(
        domain="cti",
        scope_id="s",
        snapshot_id=manifest.generation_id,
        manifest_sha256=manifest.manifest_sha256,
    )
    engine = GraphSearchEngine(
        CatalogNeighborReader(store),
        allowed_pattern_ids=frozenset({pattern.pattern_id}),
        neighbor_limit=neighbor_limit,
    )
    return engine.search(
        manifest=manifest,
        pattern=pattern,
        authorized_seed_ids=seeds,
        scope=scope,
        snapshot=snapshot,
        policy=policy or Policy(),
        deadline=time.monotonic() + 3,
        max_hops=max_hops,
    )


def test_reverse_direction_and_revision_provenance():
    store, manifest = setup_graph()
    pattern = GraphPattern(pattern_id="p", relation_sequence=("maps_to",), max_hops=1)
    result = run(store, manifest, pattern, seeds=(h("b"),))
    assert any(
        path.traversal_directions == ("reverse",) and path.ordered_node_uids[-1] == h("a")
        for path in result.paths
    )
    assert all(len(path.ordered_relation_revision_uids) == 1 for path in result.paths)


def test_two_vs_three_hops_are_bounded():
    store, manifest = setup_graph()
    pattern = GraphPattern(
        pattern_id="p3",
        relation_sequence=("maps_to",),
        max_hops=3,
        target_types=("technique",),
    )
    assert run(store, manifest, pattern, max_hops=2).paths == ()
    assert any(
        len(path.ordered_relation_revision_uids) == 3
        for path in run(store, manifest, pattern, max_hops=3).paths
    )


def test_cycles_do_not_repeat_node_revision():
    store, manifest = setup_graph(cycle=True)
    pattern = GraphPattern(pattern_id="p", relation_sequence=("maps_to",), max_hops=3)
    result = run(store, manifest, pattern, max_hops=3)
    assert all(
        len(set(path.ordered_node_revision_uids)) == len(path.ordered_node_revision_uids)
        for path in result.paths
    )


def test_high_degree_cap_is_deterministic_and_reports_truncation():
    store, manifest = setup_graph(high_degree=40)
    pattern = GraphPattern(pattern_id="p", relation_sequence=("maps_to",), max_hops=1)
    first = run(store, manifest, pattern, neighbor_limit=30)
    second = run(store, manifest, pattern, neighbor_limit=30)
    assert [item.path_id for item in first.paths] == [item.path_id for item in second.paths]
    assert len(first.paths) <= 30
    assert first.truncated and first.reason == "neighbor-budget"


def test_denied_intermediate_assertion_denies_path_extension():
    store, manifest = setup_graph()
    pattern = GraphPattern(pattern_id="p3", relation_sequence=("maps_to",), max_hops=3, target_types=("technique",))
    assert run(store, manifest, pattern, policy=Policy(frozenset({h("6")})), max_hops=3).paths == ()


def test_denied_intermediate_node_denies_path_extension():
    store, manifest = setup_graph()
    pattern = GraphPattern(pattern_id="p3", relation_sequence=("maps_to",), max_hops=3, target_types=("technique",))
    assert run(store, manifest, pattern, policy=Policy(frozenset({h("2")})), max_hops=3).paths == ()


def test_denied_support_evidence_denies_path_extension():
    store, manifest = setup_graph()
    pattern = GraphPattern(pattern_id="p3", relation_sequence=("maps_to",), max_hops=3, target_types=("technique",))
    assert run(store, manifest, pattern, policy=Policy(frozenset({h("e")})), max_hops=3).paths == ()


def test_deadline_returns_timeout_not_empty_success():
    store, manifest = setup_graph()
    pattern = GraphPattern(pattern_id="p", relation_sequence=("maps_to",), max_hops=2)
    scope = ResolvedScope(
        principal_id="p", corpus_id="c", domain="cti", scope_id="s",
        policy_version="test", source_allowlist=frozenset({"fixture"}),
        allowed_destinations=frozenset({"caller"}),
    )
    snapshot = SnapshotRef(
        domain="cti", scope_id="s", snapshot_id=manifest.generation_id,
        manifest_sha256=manifest.manifest_sha256,
    )
    engine = GraphSearchEngine(CatalogNeighborReader(store), allowed_pattern_ids=frozenset({"p"}))
    result = engine.search(
        manifest=manifest, pattern=pattern, authorized_seed_ids=(h("a"),), scope=scope,
        snapshot=snapshot, policy=Policy(), deadline=time.monotonic() - 1,
    )
    assert result.status == "timeout" and result.reason == "deadline"


def test_missing_seed_is_legitimate_no_results():
    store, manifest = setup_graph()
    pattern = GraphPattern(pattern_id="p", relation_sequence=("maps_to",), max_hops=1)
    result = run(store, manifest, pattern, seeds=(h("0"),))
    assert result.status == "no_results" and result.reason == "no-authorized-seed"


def test_unknown_pattern_rejected():
    store, manifest = setup_graph()
    pattern = GraphPattern(pattern_id="not-reviewed", relation_sequence=("maps_to",), max_hops=1)
    scope = ResolvedScope(
        principal_id="p", corpus_id="c", domain="cti", scope_id="s",
        policy_version="test", source_allowlist=frozenset({"fixture"}),
        allowed_destinations=frozenset({"caller"}),
    )
    snapshot = SnapshotRef(
        domain="cti", scope_id="s", snapshot_id=manifest.generation_id,
        manifest_sha256=manifest.manifest_sha256,
    )
    engine = GraphSearchEngine(CatalogNeighborReader(store), allowed_pattern_ids=frozenset({"reviewed"}))
    with pytest.raises(UnknownGraphPattern):
        engine.search(
            manifest=manifest, pattern=pattern, authorized_seed_ids=(h("a"),), scope=scope,
            snapshot=snapshot, policy=Policy(), deadline=time.monotonic() + 1,
        )
