from __future__ import annotations

import pytest

from packages.indexing.graph_indexer import (
    CatalogGraphProjectionWriter,
    GraphProjectionError,
    Neo4jGraphProjectionWriter,
    graph_physical_key,
    reconstruct_catalog_graph,
)
from packages.indexing.manifests import GenerationManifest, GenerationMember, ProjectionSpec


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


def obj(uid, rev, name, typ="weakness"):
    return {
        "kind": "object",
        "evidence_uid": uid,
        "revision_uid": rev,
        "payload": {"object_type": typ, "name": name, "policy": {}},
        "sources": [
            {
                "raw_sha256": h("f"),
                "source_instance": "fixture",
                "source_object_id": uid,
            }
        ],
    }


def rel(uid, rev, src, tgt, kind="explicit"):
    return {
        "relation_uid": uid,
        "revision_uid": rev,
        "payload": {
            "source_object_uid": src,
            "target_object_uid": tgt,
            "original_relation": "mapped-to",
            "normalized_relation": "maps_to",
            "assertion_kind": kind,
            "direction": "forward",
            "qualifiers": [],
            "source_field_path": "x",
            "policy": {},
        },
        "sources": [
            {
                "raw_sha256": h("e"),
                "source_instance": "fixture",
                "source_object_id": uid,
            }
        ],
    }


def manifest(store, *, include_c=True):
    a, b, c = h("a"), h("b"), h("c")
    ar, br, cr = h("1"), h("2"), h("3")
    r1, r2, rr1, rr2 = h("d"), h("4"), h("5"), h("6")
    store.objects[ar] = obj(a, ar, "same", "vulnerability")
    store.objects[br] = obj(b, br, "same", "weakness")
    store.objects[cr] = obj(c, cr, "c", "attack-pattern")
    store.relations[rr1] = rel(r1, rr1, a, b)
    store.relations[rr2] = rel(r2, rr2, a, b, "catalog_mapping")
    members = [
        GenerationMember(kind="object", evidence_uid=a, revision_uid=ar),
        GenerationMember(kind="object", evidence_uid=b, revision_uid=br),
        GenerationMember(kind="relation", evidence_uid=r1, revision_uid=rr1),
        GenerationMember(kind="relation", evidence_uid=r2, revision_uid=rr2),
    ]
    if include_c:
        members.append(GenerationMember(kind="object", evidence_uid=c, revision_uid=cr))
    writer = CatalogGraphProjectionWriter(store)
    result = GenerationManifest(
        generation_id=h("9"),
        domain="cti",
        scope_id="s",
        corpus_id="c",
        membership=tuple(sorted(members, key=lambda m: (m.kind, m.evidence_uid, m.revision_uid))),
        projections=(
            ProjectionSpec(
                backend="graph", enabled=True, required=True, fingerprint=writer.fingerprint
            ),
        ),
        fingerprints={},
    )
    return result, writer


def test_catalog_projection_preserves_parallel_assertions_and_same_name_nodes():
    store = Store()
    generation, writer = manifest(store)
    graph = reconstruct_catalog_graph(store, generation)
    assert len(graph.objects) == 3
    assert [item.name for item in graph.objects].count("same") == 2
    assert len(graph.assertions) == 2
    assert len({item.revision_uid for item in graph.assertions}) == 2
    receipt = writer.build(generation)
    assert receipt.visibility_verified
    assert writer.verify(generation, receipt)


def test_mixed_generation_endpoint_rejected():
    store = Store()
    generation, _ = manifest(store, include_c=False)
    store.relations[h("5")] = rel(h("d"), h("5"), h("a"), h("c"))
    with pytest.raises(GraphProjectionError, match="endpoint"):
        reconstruct_catalog_graph(store, generation)


class FakeNeo4j:
    def __init__(self):
        self.writes = []
        self.visible = {
            "generation_id": h("9"),
            "manifest_sha256": None,
            "object_count": 3,
            "assertion_count": 2,
        }

    def execute_write(self, query, parameters):
        self.writes.append((query, parameters))
        return []

    def execute_read(self, query, parameters):
        return [dict(self.visible)]


def test_neo4j_projection_is_non_destructive_and_idempotent_queries_only_merge():
    store = Store()
    generation, _ = manifest(store)
    client = FakeNeo4j()
    writer = Neo4jGraphProjectionWriter(store, client, backend_identity="advanced-neo4j")
    generation = generation.model_copy(
        update={
            "projections": (
                ProjectionSpec(
                    backend="graph",
                    enabled=True,
                    required=True,
                    fingerprint=writer.fingerprint,
                ),
            )
        }
    )
    client.visible["manifest_sha256"] = generation.manifest_sha256
    first = writer.build(generation)
    second = writer.build(generation)
    cypher = "\n".join(query for query, _ in client.writes).upper()
    assert "MERGE" in cypher
    assert "DETACH DELETE" not in cypher
    assert "DELETE " not in cypher
    assert first.artifact_sha256 == second.artifact_sha256
    assert writer.verify(generation, second)


def test_legacy_backend_identity_rejected():
    with pytest.raises(GraphProjectionError):
        Neo4jGraphProjectionWriter(Store(), FakeNeo4j(), backend_identity="legacy")


def test_physical_keys_preserve_scope_domain_and_revision_identity():
    old, new = h("1"), h("2")
    assert graph_physical_key("cti", "scope-a", old) != graph_physical_key(
        "cti", "scope-a", new
    )
    assert graph_physical_key("cti", "scope-a", old) != graph_physical_key(
        "cti", "scope-b", old
    )
    assert graph_physical_key("cti", "scope-a", old) != graph_physical_key(
        "other", "scope-a", old
    )
