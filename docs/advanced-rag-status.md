# Advanced RAG V3 implementation status

Updated: 2026-09-17. Prompt 09 documented head / Prompt 10 predecessor: `b76830493d41bb0b6931187ffbd8a406299aedb3`. Current stacked branch: `feat/advanced-10-neo4j-evidence-projection`. Legacy graph/retrieval/Milvus/API/session behavior remains available and unchanged.

## Prompt 10 - revision-preserving graph projection and bounded traversal

Implemented beside the legacy graph stack:

- immutable object-revision and assertion-revision graph identities; physical keys hash domain + scope + immutable revision/generation identity, while logical object/relation UIDs remain explicit properties;
- source -> assertion -> target representation, preserving original/normalized relation, assertion kind, direction, qualifiers, source field and supporting evidence references;
- `reconstruct_catalog_graph()` verifies every projected object/relation revision against one pinned Prompt 06 generation and rejects mixed-generation/dangling endpoints;
- `CatalogGraphProjectionWriter` provides the offline fixture/correctness graph projection and emits Prompt 06 receipts without a Neo4j connection;
- injected `Neo4jGraphProjectionWriter` uses fixed labels and fixed parameterized Cypher templates only, performs non-destructive MERGE/upsert, exposes no delete/recreate path, and verifies generation visibility before producing a usable receipt;
- one shared `GraphSearchEngine` serves catalog-backed and Neo4j-backed neighbor readers. It enforces maximum 8 seeds, 30 logical neighbors per expansion, 40 paths, 1000 visited nodes and at most 3 hops; traversal ordering is deterministic before caps;
- reverse traversal, node revisions, assertion revisions and support evidence survive in `EvidencePath`; a stored assertion remains one logical hop although Neo4j represents it with two fixed edges;
- every target node, assertion and raw supporting evidence view is authorized before path extension; any denial removes the whole extension;
- missing authorized seeds are legitimate no-results, unknown pattern IDs are rejected, timeout/cancellation are explicit, and Neo4j read failures become backend-unavailable errors rather than empty results;
- fixture ingestion now publishes exact + lexical + deterministic dense + catalog graph projections in one Prompt 06 publication flow. Restart validation reloads the generation/receipt from the catalog and reconstructs graph adjacency from pinned membership;
- isolated `advanced-neo4j` service uses Neo4j 5.15 Community, dedicated loopback ports, network, volumes and mandatory advanced credentials. Labels/multi-database support are not considered a security boundary;
- `tests/integration/test_advanced_neo4j.py` separately checks server version, advanced connectivity, optional rejection of legacy credentials on the advanced endpoint, and optional legacy-endpoint invisibility of an advanced probe.

### Prompt 10 focused validation

Available implementation sandbox: Python 3.13.5 and a partial compatibility workspace. Repository target remains Python 3.11.

```text
PYTHONPATH=. python -m pytest \
  tests/unit/indexing/test_graph_projection.py \
  tests/unit/retrieval/test_graph_paths.py -q
15 passed
```

The broader Prompt 10 + Prompt 11 local mechanics run later in the same implementation session passed `33` tests. This is not a substitute for the exact Python 3.11 full-checkout exit chain.

Real Neo4j commands remain `not_run` in the implementation sandbox because Docker/service credentials are unavailable:

```text
docker compose -f deploy/advanced-services.compose.yml up -d advanced-neo4j
python -m pytest tests/integration/test_advanced_neo4j.py -m integration -q
```

The pre-existing Prompt 06/07 fixture E2E assertion was stale after later phases added required dense publication. Prompt 10 reconciles that predecessor validation surface to the current exact/lexical/dense/graph fixture generation instead of falsely inheriting its old expectation.

## Earlier unresolved correctness/service gates

The following remain to be executed from a complete Python 3.11 checkout and are intentionally not inferred from sandbox results:

- exact Prompt 04/05 Python 3.11 focused gates;
- `scripts/validate_advanced_06_07.py` on the current stack;
- `scripts/validate_advanced_08_09.py` on the current stack;
- full repository pytest collection on the current stack;
- real Milvus compatibility/legacy isolation;
- real Neo4j compatibility/legacy isolation;
- any retrieval-quality promotion gate.

Prompt 11 adds a single fail-fast chained validator that includes these previously unresolved correctness gates where the prerequisites are locally available.

## Next-phase readiness

Prompt 10 offline correctness mechanics are implemented. Prompt 11 may proceed from the documented Prompt 10 handoff because its deterministic planner depends on the reviewed graph patterns and bounded graph interface, not on a live Neo4j service. Real service deployment/promotion remains independently blocked until its integration gates pass.