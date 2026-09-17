"""Bounded, revision-pinned graph traversal for the advanced retrieval path."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Protocol

from packages.evidence.domain import GraphPattern
from packages.evidence.ids import path_uid
from packages.evidence.policy import ResolvedScope, RetrievalPolicy, authorize_evidence_set
from packages.evidence.schema import AuthorizedEvidenceView, EvidencePath, EvidencePolicyMetadata, SnapshotRef
from packages.indexing.graph_indexer import GraphProjectionError, graph_physical_key, reconstruct_catalog_graph
from packages.indexing.manifests import GenerationManifest


class GraphRetrievalError(RuntimeError):
    pass


class GraphBackendUnavailable(GraphRetrievalError):
    pass


class UnknownGraphPattern(GraphRetrievalError):
    pass


@dataclass(frozen=True)
class GraphNeighbor:
    from_object_uid: str
    from_revision_uid: str
    to_object_uid: str
    to_revision_uid: str
    to_object_type: str
    assertion_uid: str
    assertion_revision_uid: str
    normalized_relation: str
    assertion_kind: str
    assertion_direction: str
    traversal_direction: str
    authorization_views: tuple[AuthorizedEvidenceView, ...]
    support_evidence_uids: tuple[str, ...]


class NeighborReader(Protocol):
    def neighbors(
        self,
        *,
        manifest: GenerationManifest,
        node_revision_uid: str,
        allowed_relations: frozenset[str],
        limit: int,
        deadline: float,
    ) -> tuple[GraphNeighbor, ...]: ...


def _policy(payload: dict[str, Any]) -> EvidencePolicyMetadata:
    return EvidencePolicyMetadata.model_validate(payload.get("policy") or {})


def _object_view(row: dict[str, Any], *, domain: str, scope_id: str) -> AuthorizedEvidenceView:
    sources = row.get("sources") or []
    return AuthorizedEvidenceView(
        evidence_uid=row["revision_uid"],
        domain=domain,
        scope_id=scope_id,
        source_instances=tuple(sorted({str(s["source_instance"]) for s in sources if s.get("source_instance")})),
        policy=_policy(row["payload"]),
    )


def _assertion_views(row: dict[str, Any], *, domain: str, scope_id: str) -> tuple[AuthorizedEvidenceView, ...]:
    sources = row.get("sources") or []
    source_instances = tuple(sorted({str(s["source_instance"]) for s in sources if s.get("source_instance")}))
    policy = _policy(row["payload"])
    views = [
        AuthorizedEvidenceView(
            evidence_uid=row["revision_uid"],
            domain=domain,
            scope_id=scope_id,
            source_instances=source_instances,
            policy=policy,
        )
    ]
    for source in sources:
        raw_sha = source.get("raw_sha256")
        if raw_sha:
            views.append(
                AuthorizedEvidenceView(
                    evidence_uid=str(raw_sha),
                    domain=domain,
                    scope_id=scope_id,
                    source_instances=(str(source.get("source_instance", "")),),
                    policy=policy,
                )
            )
    return tuple(views)


def _support_uids(assertion_revision_uid: str, row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                assertion_revision_uid,
                *(
                    str(item["raw_sha256"])
                    for item in row.get("sources") or []
                    if item.get("raw_sha256")
                ),
            }
        )
    )


class CatalogNeighborReader:
    """Restart-safe adjacency reconstructed only from the pinned catalog generation."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def neighbors(self, *, manifest, node_revision_uid, allowed_relations, limit, deadline):
        if time.monotonic() >= deadline:
            raise TimeoutError("graph deadline exceeded before catalog adjacency read")
        if limit < 1:
            return ()
        try:
            graph = reconstruct_catalog_graph(self.store, manifest)
        except GraphProjectionError as exc:
            raise GraphBackendUnavailable(str(exc)) from exc
        objects = {row.revision_uid: row for row in graph.objects}
        if node_revision_uid not in objects:
            return ()
        result: list[GraphNeighbor] = []
        for assertion in graph.assertions:
            if assertion.normalized_relation not in allowed_relations:
                continue
            if assertion.source_revision_uid == node_revision_uid:
                other_uid, other_revision, traversal = (
                    assertion.target_object_uid,
                    assertion.target_revision_uid,
                    "forward",
                )
            elif assertion.target_revision_uid == node_revision_uid:
                other_uid, other_revision, traversal = (
                    assertion.source_object_uid,
                    assertion.source_revision_uid,
                    "reverse",
                )
            else:
                continue
            target = self.store.get_revision(manifest.domain, manifest.scope_id, other_revision)
            assertion_row = self.store.get_assertion(manifest.domain, manifest.scope_id, assertion.revision_uid)
            if target is None or assertion_row is None:
                raise GraphBackendUnavailable("catalog adjacency disappeared during pinned traversal")
            views = (
                _object_view(target, domain=manifest.domain, scope_id=manifest.scope_id),
                *_assertion_views(assertion_row, domain=manifest.domain, scope_id=manifest.scope_id),
            )
            result.append(
                GraphNeighbor(
                    from_object_uid=objects[node_revision_uid].object_uid,
                    from_revision_uid=node_revision_uid,
                    to_object_uid=other_uid,
                    to_revision_uid=other_revision,
                    to_object_type=str(target["payload"].get("object_type", "unknown")),
                    assertion_uid=assertion.relation_uid,
                    assertion_revision_uid=assertion.revision_uid,
                    normalized_relation=assertion.normalized_relation,
                    assertion_kind=assertion.assertion_kind,
                    assertion_direction=assertion.direction,
                    traversal_direction=traversal,
                    authorization_views=views,
                    support_evidence_uids=_support_uids(assertion.revision_uid, assertion_row),
                )
            )
        result.sort(
            key=lambda item: (
                item.normalized_relation,
                item.assertion_revision_uid,
                item.to_revision_uid,
                item.traversal_direction,
            )
        )
        return tuple(result[:limit])


_NEO4J_NEIGHBOR_QUERY = """
MATCH (g:AdvancedEvidenceGeneration {physical_key:$generation_key})
MATCH (g)-[:ADVANCED_CONTAINS_OBJECT]->(seed:AdvancedEvidenceObjectRevision {physical_key:$seed_key})
MATCH (g)-[:ADVANCED_CONTAINS_ASSERTION]->(a:AdvancedEvidenceAssertionRevision)
MATCH (g)-[:ADVANCED_CONTAINS_OBJECT]->(other:AdvancedEvidenceObjectRevision)
WHERE a.normalized_relation IN $allowed_relations AND (
  ((seed)-[:ADVANCED_ASSERTS_SOURCE]->(a)-[:ADVANCED_ASSERTS_TARGET]->(other)) OR
  ((other)-[:ADVANCED_ASSERTS_SOURCE]->(a)-[:ADVANCED_ASSERTS_TARGET]->(seed))
)
RETURN seed.object_uid AS from_object_uid, seed.revision_uid AS from_revision_uid,
       other.object_uid AS to_object_uid, other.revision_uid AS to_revision_uid,
       other.object_type AS to_object_type, a.relation_uid AS assertion_uid,
       a.revision_uid AS assertion_revision_uid, a.normalized_relation AS normalized_relation,
       a.assertion_kind AS assertion_kind, a.direction AS assertion_direction,
       CASE WHEN (seed)-[:ADVANCED_ASSERTS_SOURCE]->(a) THEN 'forward' ELSE 'reverse' END AS traversal_direction
ORDER BY normalized_relation, assertion_revision_uid, to_revision_uid, traversal_direction
LIMIT $limit
""".strip()


class Neo4jNeighborReader:
    """Fixed-template Neo4j adjacency reader; callers never supply Cypher."""

    def __init__(self, client: Any, store: Any) -> None:
        self.client = client
        self.store = store

    def neighbors(self, *, manifest, node_revision_uid, allowed_relations, limit, deadline):
        if time.monotonic() >= deadline:
            raise TimeoutError("graph deadline exceeded before Neo4j adjacency read")
        try:
            rows = self.client.execute_read(
                _NEO4J_NEIGHBOR_QUERY,
                {
                    "generation_key": graph_physical_key(manifest.domain, manifest.scope_id, manifest.generation_id),
                    "seed_key": graph_physical_key(manifest.domain, manifest.scope_id, node_revision_uid),
                    "allowed_relations": sorted(allowed_relations),
                    "limit": int(limit),
                },
            )
        except Exception as exc:
            raise GraphBackendUnavailable("Neo4j adjacency read failed") from exc
        result: list[GraphNeighbor] = []
        object_members = {
            (m.evidence_uid, m.revision_uid) for m in manifest.membership if m.kind == "object"
        }
        relation_members = {
            (m.evidence_uid, m.revision_uid) for m in manifest.membership if m.kind == "relation"
        }
        for raw in rows:
            to_uid, to_revision = str(raw["to_object_uid"]), str(raw["to_revision_uid"])
            assertion_uid, assertion_revision = str(raw["assertion_uid"]), str(raw["assertion_revision_uid"])
            if (to_uid, to_revision) not in object_members or (assertion_uid, assertion_revision) not in relation_members:
                continue
            target = self.store.get_revision(manifest.domain, manifest.scope_id, to_revision)
            assertion = self.store.get_assertion(manifest.domain, manifest.scope_id, assertion_revision)
            if target is None or assertion is None:
                continue
            result.append(
                GraphNeighbor(
                    from_object_uid=str(raw["from_object_uid"]),
                    from_revision_uid=str(raw["from_revision_uid"]),
                    to_object_uid=to_uid,
                    to_revision_uid=to_revision,
                    to_object_type=str(raw.get("to_object_type") or "unknown"),
                    assertion_uid=assertion_uid,
                    assertion_revision_uid=assertion_revision,
                    normalized_relation=str(raw["normalized_relation"]),
                    assertion_kind=str(raw["assertion_kind"]),
                    assertion_direction=str(raw["assertion_direction"]),
                    traversal_direction=str(raw["traversal_direction"]),
                    authorization_views=(
                        _object_view(target, domain=manifest.domain, scope_id=manifest.scope_id),
                        *_assertion_views(assertion, domain=manifest.domain, scope_id=manifest.scope_id),
                    ),
                    support_evidence_uids=_support_uids(assertion_revision, assertion),
                )
            )
        result.sort(
            key=lambda item: (
                item.normalized_relation,
                item.assertion_revision_uid,
                item.to_revision_uid,
                item.traversal_direction,
            )
        )
        return tuple(result[:limit])


@dataclass(frozen=True)
class GraphSearchResult:
    status: str
    paths: tuple[EvidencePath, ...]
    truncated: bool = False
    reason: str | None = None
    visited_nodes: int = 0


class GraphSearchEngine:
    """Shared bounded traversal for catalog-backed and Neo4j-backed readers."""

    def __init__(
        self,
        reader: NeighborReader,
        *,
        allowed_pattern_ids: frozenset[str],
        max_seeds: int = 8,
        neighbor_limit: int = 30,
        path_limit: int = 40,
        max_visited_nodes: int = 1000,
    ) -> None:
        if not (1 <= max_seeds <= 8 and 1 <= neighbor_limit <= 30 and 1 <= path_limit <= 40):
            raise ValueError("graph limits exceed reviewed bounds")
        if not (1 <= max_visited_nodes <= 1000):
            raise ValueError("visited-node budget exceeds reviewed bound")
        self.reader = reader
        self.allowed_pattern_ids = allowed_pattern_ids
        self.max_seeds = max_seeds
        self.neighbor_limit = neighbor_limit
        self.path_limit = path_limit
        self.max_visited_nodes = max_visited_nodes

    def search(
        self,
        *,
        manifest: GenerationManifest,
        pattern: GraphPattern,
        authorized_seed_ids: tuple[str, ...],
        scope: ResolvedScope,
        snapshot: SnapshotRef,
        policy: RetrievalPolicy,
        deadline: float,
        max_hops: int | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> GraphSearchResult:
        if pattern.pattern_id not in self.allowed_pattern_ids:
            raise UnknownGraphPattern(pattern.pattern_id)
        if (scope.domain, scope.scope_id, scope.corpus_id) != (
            manifest.domain,
            manifest.scope_id,
            manifest.corpus_id,
        ):
            raise GraphRetrievalError("resolved scope does not match graph generation")
        if (snapshot.domain, snapshot.scope_id, snapshot.snapshot_id, snapshot.manifest_sha256) != (
            manifest.domain,
            manifest.scope_id,
            manifest.generation_id,
            manifest.manifest_sha256,
        ):
            raise GraphRetrievalError("snapshot does not match graph generation")
        requested_hops = pattern.max_hops if max_hops is None else max_hops
        if requested_hops < 0 or requested_hops > 3:
            raise ValueError("max_hops must be between 0 and 3")
        hop_limit = min(pattern.max_hops, requested_hops)
        if hop_limit == 0:
            return GraphSearchResult(status="no_results", paths=())
        allowed_relations = frozenset(pattern.relation_sequence)
        if not allowed_relations:
            raise UnknownGraphPattern("pattern has no reviewed relations")

        object_members = {
            member.evidence_uid: member.revision_uid
            for member in manifest.membership
            if member.kind == "object"
        }
        seeds: list[tuple[str, str]] = []
        for object_uid in authorized_seed_ids[: self.max_seeds]:
            revision_uid = object_members.get(object_uid)
            if revision_uid is None:
                continue
            store = getattr(self.reader, "store", None)
            if store is not None:
                revision = store.get_revision(manifest.domain, manifest.scope_id, revision_uid)
                if revision is None:
                    continue
                if not policy.authorize_evidence(
                    _object_view(revision, domain=manifest.domain, scope_id=manifest.scope_id),
                    scope,
                    "caller",
                ).allowed:
                    continue
            seeds.append((object_uid, revision_uid))
        if not seeds:
            return GraphSearchResult(status="no_results", paths=(), reason="no-authorized-seed")

        frontier = [([uid], [rev], [], [], set()) for uid, rev in sorted(seeds, key=lambda x: (x[1], x[0]))]
        output: list[EvidencePath] = []
        visited = {revision for _, revision in seeds}
        truncated = False
        reason: str | None = None

        for depth in range(1, hop_limit + 1):
            next_frontier = []
            for object_uids, revision_uids, relation_revisions, directions, supports in frontier:
                if cancelled and cancelled():
                    return GraphSearchResult("timeout", tuple(output), True, "cancelled", len(visited))
                if time.monotonic() >= deadline:
                    return GraphSearchResult("timeout", tuple(output), True, "deadline", len(visited))
                try:
                    neighbors = self.reader.neighbors(
                        manifest=manifest,
                        node_revision_uid=revision_uids[-1],
                        allowed_relations=allowed_relations,
                        limit=self.neighbor_limit + 1,
                        deadline=deadline,
                    )
                except TimeoutError:
                    return GraphSearchResult("timeout", tuple(output), True, "deadline", len(visited))
                if len(neighbors) > self.neighbor_limit:
                    truncated = True
                    reason = reason or "neighbor-budget"
                    neighbors = neighbors[: self.neighbor_limit]
                for neighbor in neighbors:
                    if neighbor.to_revision_uid in revision_uids:
                        continue
                    if not authorize_evidence_set(policy, neighbor.authorization_views, scope, "caller").allowed:
                        continue
                    if len(visited) >= self.max_visited_nodes and neighbor.to_revision_uid not in visited:
                        truncated, reason = True, "visited-node-budget"
                        break
                    visited.add(neighbor.to_revision_uid)
                    new_objects = [*object_uids, neighbor.to_object_uid]
                    new_revisions = [*revision_uids, neighbor.to_revision_uid]
                    new_relations = [*relation_revisions, neighbor.assertion_revision_uid]
                    new_directions = [*directions, neighbor.traversal_direction]
                    new_supports = set(supports)
                    new_supports.update(neighbor.support_evidence_uids)
                    if not pattern.target_types or neighbor.to_object_type in pattern.target_types:
                        output.append(
                            EvidencePath(
                                path_id=path_uid(new_objects, new_relations, new_directions),
                                domain=manifest.domain,
                                scope_id=manifest.scope_id,
                                snapshot=snapshot,
                                ordered_node_uids=tuple(new_objects),
                                ordered_node_revision_uids=tuple(new_revisions),
                                ordered_relation_revision_uids=tuple(new_relations),
                                traversal_directions=tuple(new_directions),
                                support_evidence_uids=tuple(sorted(new_supports)),
                                source_refs=(),
                                domains_traversed=(manifest.domain,),
                            )
                        )
                        if len(output) >= self.path_limit:
                            return GraphSearchResult("ok", tuple(output), True, "path-budget", len(visited))
                    if depth < hop_limit:
                        next_frontier.append((new_objects, new_revisions, new_relations, new_directions, new_supports))
                if reason == "visited-node-budget":
                    break
            frontier = next_frontier
            if reason == "visited-node-budget" or (not frontier and depth < hop_limit):
                break
        output.sort(key=lambda path: (len(path.ordered_relation_revision_uids), path.path_id))
        return GraphSearchResult(
            status="ok" if output else "no_results",
            paths=tuple(output[: self.path_limit]),
            truncated=truncated,
            reason=reason,
            visited_nodes=len(visited),
        )


__all__ = [
    "CatalogNeighborReader",
    "GraphBackendUnavailable",
    "GraphNeighbor",
    "GraphRetrievalError",
    "GraphSearchEngine",
    "GraphSearchResult",
    "NeighborReader",
    "Neo4jNeighborReader",
    "UnknownGraphPattern",
]
