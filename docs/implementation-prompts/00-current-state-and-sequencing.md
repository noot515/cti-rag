# Current state and sequencing handoff

Prompt 10 begins from Prompt 09 documented head `b76830493d41bb0b6931187ffbd8a406299aedb3` and is stacked on `feat/advanced-10-neo4j-evidence-projection`.

Reconciliation notes:

1. Prompt 06 remains the publication authority. Both catalog-backed and Neo4j graph writers satisfy the existing `ProjectionWriter`/`ProjectionReceipt` contract; Prompt 10 introduces no second active pointer.
2. Prompt 05 SQLite membership remains authoritative. Graph projection reconstructs exact object/relation revisions from the pinned generation and rejects a relation when either endpoint revision is absent from that manifest.
3. Physical graph keys include domain + scope + immutable revision/generation identity. Names are ordinary properties and never graph identity, so equal names and old/new revisions remain distinct.
4. An evidence assertion is a first-class revision node. Neo4j stores source -> assertion -> target as two fixed edges, but traversal treats the assertion as one logical hop and returns its revision identity and support evidence.
5. Neo4j writes use fixed labels/templates and parameterized values only. The advanced writer exposes no arbitrary Cypher or destructive drop/delete operation.
6. `GraphSearchEngine` is backend-independent. `CatalogNeighborReader` reconstructs restart-safe fixture adjacency from the catalog; `Neo4jNeighborReader` uses one fixed one-hop query and then rechecks results against pinned catalog membership.
7. Reviewed CTI `GraphPattern`s remain domain-owned. Ordinary traversal remains bounded to two hops unless an explicit allowlisted three-hop mapping pattern is selected; Prompt 11 makes this distinction explicit in query planning.
8. Search budgets are capped at 8 seeds, 30 logical neighbors per expansion, 40 paths, 1000 visited nodes and 3 hops. Ordering occurs before truncation. Timeout/cancellation and backend failure are distinct from successful empty evidence.
9. Every target node, assertion and raw support view is authorized before path extension. One denied component denies the whole extension.
10. Fixture publication now requires exact, lexical, deterministic dense and catalog graph projections and remains fully offline. This also reconciles the predecessor P06/P07 E2E fixture assertion that had become stale after P08 introduced required dense publication.
11. The real `advanced-neo4j` service is a separate Neo4j 5.15 Community container with unique loopback ports, internal network, volumes and mandatory advanced credentials. Labels and Community database behavior are not considered isolation controls.
12. Real-service tests are separate and require explicit `ADVANCED_NEO4J_INTEGRATION_URI`, advanced credentials and optional legacy endpoint/credentials. No service was started in the implementation sandbox.
13. Focused Prompt 10 local mechanics validation passed (`15 passed`) on Python 3.13.5 compatibility workspace. Exact Python 3.11/full-checkout and live service gates remain `not_run`.
14. Prompt 11 may proceed offline because it depends on reviewed graph contracts/patterns, not a live Neo4j deployment. The Prompt 11 handoff must chain the still-unrun Prompt 04/05, Prompt 06/07 and Prompt 08/09 Python 3.11 correctness gates where prerequisites are available.
