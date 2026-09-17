"""Revision-preserving advanced graph projection contracts.

The catalog-backed writer is the fixture/default correctness implementation.  The
Neo4j writer is injected-client only and uses fixed Cypher templates; importing
this module never imports a Neo4j SDK or opens a network connection.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol

from packages.evidence.ids import canonical_hash, canonical_json
from packages.indexing.manifests import GenerationManifest, ProjectionReceipt


class GraphProjectionError(RuntimeError):
    pass


def graph_physical_key(domain: str, scope_id: str, revision_uid: str) -> str:
    """Physical graph key includes domain, scope, and immutable revision identity."""
    if not domain or not scope_id or not revision_uid:
        raise ValueError("graph physical key components must be non-empty")
    return canonical_hash(["graph-physical-v1", domain, scope_id, revision_uid])


@dataclass(frozen=True)
class GraphObjectRevision:
    object_uid: str
    revision_uid: str
    object_type: str
    name: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class GraphAssertionRevision:
    relation_uid: str
    revision_uid: str
    source_object_uid: str
    source_revision_uid: str
    target_object_uid: str
    target_revision_uid: str
    original_relation: str
    normalized_relation: str
    assertion_kind: str
    direction: str
    qualifiers_json: str
    source_field_path: str | None
    evidence_refs_json: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class GraphProjectionSnapshot:
    objects: tuple[GraphObjectRevision, ...]
    assertions: tuple[GraphAssertionRevision, ...]

    @property
    def artifact_sha256(self) -> str:
        return canonical_hash(
            [
                "catalog-graph-projection-v1",
                [
                    {
                        "object_uid": row.object_uid,
                        "revision_uid": row.revision_uid,
                        "object_type": row.object_type,
                        "name": row.name,
                    }
                    for row in self.objects
                ],
                [
                    {
                        "relation_uid": row.relation_uid,
                        "revision_uid": row.revision_uid,
                        "source_object_uid": row.source_object_uid,
                        "source_revision_uid": row.source_revision_uid,
                        "target_object_uid": row.target_object_uid,
                        "target_revision_uid": row.target_revision_uid,
                        "original_relation": row.original_relation,
                        "normalized_relation": row.normalized_relation,
                        "assertion_kind": row.assertion_kind,
                        "direction": row.direction,
                        "qualifiers_json": row.qualifiers_json,
                        "source_field_path": row.source_field_path,
                        "evidence_refs_json": row.evidence_refs_json,
                    }
                    for row in self.assertions
                ],
            ]
        )


def _membership(manifest: GenerationManifest, kind: str) -> dict[str, str]:
    return {
        member.evidence_uid: member.revision_uid
        for member in manifest.membership
        if member.kind == kind
    }


def reconstruct_catalog_graph(store: Any, manifest: GenerationManifest) -> GraphProjectionSnapshot:
    """Reconstruct exact graph adjacency from the pinned catalog generation."""
    object_members = _membership(manifest, "object")
    relation_members = _membership(manifest, "relation")
    objects: list[GraphObjectRevision] = []
    for object_uid, revision_uid in sorted(object_members.items(), key=lambda x: (x[1], x[0])):
        row = store.get_revision(manifest.domain, manifest.scope_id, revision_uid)
        if row is None or row.get("kind") != "object" or row.get("evidence_uid") != object_uid:
            raise GraphProjectionError(f"object revision missing from catalog: {revision_uid}")
        payload = dict(row["payload"])
        objects.append(
            GraphObjectRevision(
                object_uid=object_uid,
                revision_uid=revision_uid,
                object_type=str(payload.get("object_type", "unknown")),
                name=payload.get("name"),
                payload=payload,
            )
        )

    assertions: list[GraphAssertionRevision] = []
    for relation_uid, revision_uid in sorted(relation_members.items(), key=lambda x: (x[1], x[0])):
        row = store.get_assertion(manifest.domain, manifest.scope_id, revision_uid)
        if row is None or row.get("relation_uid") != relation_uid:
            raise GraphProjectionError(f"assertion revision missing from catalog: {revision_uid}")
        payload = dict(row["payload"])
        source_uid = str(payload.get("source_object_uid", ""))
        target_uid = str(payload.get("target_object_uid", ""))
        if source_uid not in object_members or target_uid not in object_members:
            raise GraphProjectionError(f"assertion endpoint is not pinned in generation: {revision_uid}")
        evidence_refs = row.get("sources") or []
        assertions.append(
            GraphAssertionRevision(
                relation_uid=relation_uid,
                revision_uid=revision_uid,
                source_object_uid=source_uid,
                source_revision_uid=object_members[source_uid],
                target_object_uid=target_uid,
                target_revision_uid=object_members[target_uid],
                original_relation=str(payload.get("original_relation", "unknown")),
                normalized_relation=str(payload.get("normalized_relation", "unknown")),
                assertion_kind=str(payload.get("assertion_kind", "unknown")),
                direction=str(payload.get("direction", "forward")),
                qualifiers_json=canonical_json(payload.get("qualifiers") or []),
                source_field_path=payload.get("source_field_path"),
                evidence_refs_json=canonical_json(evidence_refs),
                payload=payload,
            )
        )
    return GraphProjectionSnapshot(objects=tuple(objects), assertions=tuple(assertions))


class CatalogGraphProjectionWriter:
    backend = "graph"

    def __init__(self, store: Any) -> None:
        self.store = store
        self.fingerprint = canonical_hash(
            ["catalog-graph-projection-writer-v1", "revision-preserving", "source-assertion-target"]
        )

    def build(self, manifest: GenerationManifest) -> ProjectionReceipt:
        spec = next((p for p in manifest.enabled_projections if p.backend == self.backend), None)
        if spec is None or spec.fingerprint != self.fingerprint:
            raise GraphProjectionError("graph projection fingerprint does not match manifest")
        graph = reconstruct_catalog_graph(self.store, manifest)
        return ProjectionReceipt(
            generation_id=manifest.generation_id,
            domain=manifest.domain,
            scope_id=manifest.scope_id,
            corpus_id=manifest.corpus_id,
            backend="graph",
            manifest_sha256=manifest.manifest_sha256,
            membership_sha256=manifest.membership_sha256,
            member_count=len(manifest.membership),
            fingerprint=self.fingerprint,
            artifact_sha256=graph.artifact_sha256,
            visibility_verified=True,
            sentinel=f"catalog-graph:{len(graph.objects)}:{len(graph.assertions)}:{graph.artifact_sha256[:16]}",
        )

    def verify(self, manifest: GenerationManifest, receipt: ProjectionReceipt) -> bool:
        try:
            graph = reconstruct_catalog_graph(self.store, manifest)
        except GraphProjectionError:
            return False
        return (
            receipt.backend == "graph"
            and receipt.generation_id == manifest.generation_id
            and receipt.manifest_sha256 == manifest.manifest_sha256
            and receipt.membership_sha256 == manifest.membership_sha256
            and receipt.member_count == len(manifest.membership)
            and receipt.fingerprint == self.fingerprint
            and receipt.artifact_sha256 == graph.artifact_sha256
            and receipt.sentinel == f"catalog-graph:{len(graph.objects)}:{len(graph.assertions)}:{graph.artifact_sha256[:16]}"
            and receipt.visibility_verified
        )


class Neo4jClient(Protocol):
    def execute_write(self, cypher: str, parameters: dict[str, Any]) -> Any: ...
    def execute_read(self, cypher: str, parameters: dict[str, Any]) -> list[dict[str, Any]]: ...


_CREATE_CONSTRAINTS = (
    "CREATE CONSTRAINT advanced_object_revision_key IF NOT EXISTS FOR (n:AdvancedEvidenceObjectRevision) REQUIRE n.physical_key IS UNIQUE",
    "CREATE CONSTRAINT advanced_assertion_revision_key IF NOT EXISTS FOR (n:AdvancedEvidenceAssertionRevision) REQUIRE n.physical_key IS UNIQUE",
    "CREATE CONSTRAINT advanced_generation_key IF NOT EXISTS FOR (n:AdvancedEvidenceGeneration) REQUIRE n.physical_key IS UNIQUE",
)

_UPSERT_OBJECTS = """
UNWIND $rows AS row
MERGE (n:AdvancedEvidenceObjectRevision {physical_key: row.physical_key})
ON CREATE SET n.domain=row.domain, n.scope_id=row.scope_id, n.object_uid=row.object_uid,
              n.revision_uid=row.revision_uid, n.object_type=row.object_type, n.name=row.name
RETURN count(n) AS count
""".strip()

_UPSERT_ASSERTIONS = """
UNWIND $rows AS row
MATCH (s:AdvancedEvidenceObjectRevision {physical_key: row.source_physical_key})
MATCH (t:AdvancedEvidenceObjectRevision {physical_key: row.target_physical_key})
MERGE (a:AdvancedEvidenceAssertionRevision {physical_key: row.physical_key})
ON CREATE SET a.domain=row.domain, a.scope_id=row.scope_id, a.relation_uid=row.relation_uid,
              a.revision_uid=row.revision_uid, a.original_relation=row.original_relation,
              a.normalized_relation=row.normalized_relation, a.assertion_kind=row.assertion_kind,
              a.direction=row.direction, a.qualifiers_json=row.qualifiers_json,
              a.source_field_path=row.source_field_path, a.evidence_refs_json=row.evidence_refs_json
MERGE (s)-[:ADVANCED_ASSERTS_SOURCE]->(a)
MERGE (a)-[:ADVANCED_ASSERTS_TARGET]->(t)
RETURN count(a) AS count
""".strip()

_ATTACH_GENERATION = """
MERGE (g:AdvancedEvidenceGeneration {physical_key: $generation_physical_key})
ON CREATE SET g.domain=$domain, g.scope_id=$scope_id, g.corpus_id=$corpus_id,
              g.generation_id=$generation_id, g.manifest_sha256=$manifest_sha256
WITH g
UNWIND $object_keys AS k
MATCH (n:AdvancedEvidenceObjectRevision {physical_key:k})
MERGE (g)-[:ADVANCED_CONTAINS_OBJECT]->(n)
WITH DISTINCT g
UNWIND $assertion_keys AS k
MATCH (a:AdvancedEvidenceAssertionRevision {physical_key:k})
MERGE (g)-[:ADVANCED_CONTAINS_ASSERTION]->(a)
RETURN g.generation_id AS generation_id
""".strip()

_VERIFY_GENERATION = """
MATCH (g:AdvancedEvidenceGeneration {physical_key:$generation_physical_key})
OPTIONAL MATCH (g)-[:ADVANCED_CONTAINS_OBJECT]->(n:AdvancedEvidenceObjectRevision)
WITH g, count(DISTINCT n) AS object_count
OPTIONAL MATCH (g)-[:ADVANCED_CONTAINS_ASSERTION]->(a:AdvancedEvidenceAssertionRevision)
RETURN g.generation_id AS generation_id, g.manifest_sha256 AS manifest_sha256,
       object_count, count(DISTINCT a) AS assertion_count
""".strip()


class Neo4jGraphProjectionWriter:
    backend = "graph"

    def __init__(self, store: Any, client: Neo4jClient, *, backend_identity: str) -> None:
        if not backend_identity or backend_identity == "legacy":
            raise GraphProjectionError("advanced Neo4j backend identity must be explicit and non-legacy")
        self.store = store
        self.client = client
        self.backend_identity = backend_identity
        self.fingerprint = canonical_hash(["neo4j-graph-projection-v1", backend_identity, "neo4j-5.15-community"])

    def _rows(self, manifest: GenerationManifest):
        graph = reconstruct_catalog_graph(self.store, manifest)
        objects = [
            {
                "physical_key": graph_physical_key(manifest.domain, manifest.scope_id, row.revision_uid),
                "domain": manifest.domain,
                "scope_id": manifest.scope_id,
                "object_uid": row.object_uid,
                "revision_uid": row.revision_uid,
                "object_type": row.object_type,
                "name": row.name,
            }
            for row in graph.objects
        ]
        assertions = [
            {
                "physical_key": graph_physical_key(manifest.domain, manifest.scope_id, row.revision_uid),
                "source_physical_key": graph_physical_key(manifest.domain, manifest.scope_id, row.source_revision_uid),
                "target_physical_key": graph_physical_key(manifest.domain, manifest.scope_id, row.target_revision_uid),
                "domain": manifest.domain,
                "scope_id": manifest.scope_id,
                "relation_uid": row.relation_uid,
                "revision_uid": row.revision_uid,
                "original_relation": row.original_relation,
                "normalized_relation": row.normalized_relation,
                "assertion_kind": row.assertion_kind,
                "direction": row.direction,
                "qualifiers_json": row.qualifiers_json,
                "source_field_path": row.source_field_path,
                "evidence_refs_json": row.evidence_refs_json,
            }
            for row in graph.assertions
        ]
        return graph, objects, assertions

    def build(self, manifest: GenerationManifest) -> ProjectionReceipt:
        spec = next((p for p in manifest.enabled_projections if p.backend == "graph"), None)
        if spec is None or spec.fingerprint != self.fingerprint:
            raise GraphProjectionError("Neo4j graph projection fingerprint does not match manifest")
        graph, objects, assertions = self._rows(manifest)
        for statement in _CREATE_CONSTRAINTS:
            self.client.execute_write(statement, {})
        self.client.execute_write(_UPSERT_OBJECTS, {"rows": objects})
        self.client.execute_write(_UPSERT_ASSERTIONS, {"rows": assertions})
        generation_key = graph_physical_key(manifest.domain, manifest.scope_id, manifest.generation_id)
        self.client.execute_write(
            _ATTACH_GENERATION,
            {
                "generation_physical_key": generation_key,
                "domain": manifest.domain,
                "scope_id": manifest.scope_id,
                "corpus_id": manifest.corpus_id,
                "generation_id": manifest.generation_id,
                "manifest_sha256": manifest.manifest_sha256,
                "object_keys": [row["physical_key"] for row in objects],
                "assertion_keys": [row["physical_key"] for row in assertions],
            },
        )
        rows = self.client.execute_read(_VERIFY_GENERATION, {"generation_physical_key": generation_key})
        visible = bool(
            rows
            and rows[0].get("generation_id") == manifest.generation_id
            and rows[0].get("manifest_sha256") == manifest.manifest_sha256
            and int(rows[0].get("object_count", -1)) == len(objects)
            and int(rows[0].get("assertion_count", -1)) == len(assertions)
        )
        artifact_sha = canonical_hash(["neo4j-graph-artifact-v1", graph.artifact_sha256, self.backend_identity])
        return ProjectionReceipt(
            generation_id=manifest.generation_id,
            domain=manifest.domain,
            scope_id=manifest.scope_id,
            corpus_id=manifest.corpus_id,
            backend="graph",
            manifest_sha256=manifest.manifest_sha256,
            membership_sha256=manifest.membership_sha256,
            member_count=len(manifest.membership),
            fingerprint=self.fingerprint,
            artifact_sha256=artifact_sha,
            visibility_verified=visible,
            sentinel=f"neo4j-graph:{len(objects)}:{len(assertions)}:{artifact_sha[:16]}",
        )

    def verify(self, manifest: GenerationManifest, receipt: ProjectionReceipt) -> bool:
        graph = reconstruct_catalog_graph(self.store, manifest)
        generation_key = graph_physical_key(manifest.domain, manifest.scope_id, manifest.generation_id)
        rows = self.client.execute_read(_VERIFY_GENERATION, {"generation_physical_key": generation_key})
        if not rows:
            return False
        artifact_sha = canonical_hash(["neo4j-graph-artifact-v1", graph.artifact_sha256, self.backend_identity])
        row = rows[0]
        return (
            row.get("generation_id") == manifest.generation_id
            and row.get("manifest_sha256") == manifest.manifest_sha256
            and int(row.get("object_count", -1)) == len(graph.objects)
            and int(row.get("assertion_count", -1)) == len(graph.assertions)
            and receipt.artifact_sha256 == artifact_sha
            and receipt.fingerprint == self.fingerprint
            and receipt.visibility_verified
        )


__all__ = [
    "CatalogGraphProjectionWriter",
    "GraphAssertionRevision",
    "GraphObjectRevision",
    "GraphProjectionError",
    "GraphProjectionSnapshot",
    "Neo4jClient",
    "Neo4jGraphProjectionWriter",
    "graph_physical_key",
    "reconstruct_catalog_graph",
]
