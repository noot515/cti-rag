# Current state and sequencing handoff

Prompt 11 begins from Prompt 10 documented head `1667ddb1d155412a46fa86c3c17acef30d76da54` on `feat/advanced-10-neo4j-evidence-projection` and is stacked on `feat/advanced-11-deterministic-query-planner`.

Reconciliation notes:

1. Query planning remains separate from policy. Principal, domain, corpus and resolved scope are trusted inputs outside `QueryPlan`; query text cannot change them.
2. Exact CTI identifiers are parsed deterministically before task planning. No model, RL cache, qrels, answer fields or provider discovery participates.
3. `CtiDomainAdapter` owns deterministic CTI task/target hints. Shared retrieval mechanics contain no CTI-specific branching.
4. Pure identifier lookup reserves exact priority. Mapping keeps exact source IDs as evidence/authorized seeds while answer targeting is handled separately.
5. Missing graph seeds disable graph only; independent lexical/dense retrieval stays enabled.
6. Alias candidates are bounded trusted candidate IDs and never become exact identity shortcuts.
7. The predecessor mapping pattern previously exposed a 3-hop cap for ordinary mapping. Prompt 11 reconciles this into `cti-catalog-mapping-2hop-v1` for normal mapping and keeps `cti-catalog-mapping-3hop-v1` only for explicit three-hop requests.
8. Even when a three-hop template is selected, the planner uses the caller's lower `max_graph_hops` cap.
9. `TargetObjectRef` / `TargetProjection` make answer identity explicit without coercing object/chunk/path evidence into one identity. Chunk targets are parent objects; mapping path targets require an explicit terminal object.
10. Mapping source seeds can remain evidence while being excluded from requested target ranking. Object metrics may deduplicate target objects by first occurrence only; no equivalence is inferred.
11. Prompt 10's graph mechanics remain the traversal authority. The planner only selects reviewed pattern IDs and bounds; it never emits Cypher.
12. `scripts/validate_advanced_04_11.py` is the current fail-fast correctness handoff. It chains the previously unresolved Prompt 04/05, 06/07 and 08/09 Python 3.11 gates before the new Prompt 10/11 gate, then compile, whitespace and full repository collection.
13. The historical Prompt 08/09 validator was reconciled so Compose parsing supplies validation-only placeholders for Prompt 10's newly mandatory Neo4j variables. This does not weaken runtime secret requirements.
14. Local compatibility results: Prompt 11 focused tests `18 passed`; combined Prompt 10/11 mechanics `33 passed`; modified modules `py_compile` passed. The sandbox is Python 3.13.5 with no Python 3.11 or Docker, so the exact chained gate and live services remain `not_run` here.
15. Real Milvus/Neo4j compatibility, legacy isolation, restricted-evidence service authentication and retrieval-quality gates remain independent release blockers. Offline mechanics do not authorize deployment or promotion.
