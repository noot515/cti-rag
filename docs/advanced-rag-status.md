# Advanced RAG V3 implementation status

Updated: 2026-09-17. Prompt 10 documented head / Prompt 11 predecessor: `1667ddb1d155412a46fa86c3c17acef30d76da54`. Current stacked branch: `feat/advanced-11-deterministic-query-planner`. Legacy retriever/entity extraction/RL candidate cache/API behavior remains unchanged.

## Prompt 10 - revision-preserving graph projection

Prompt 10 adds immutable catalog/Neo4j graph projection, fixed source -> assertion -> target representation, bounded backend-independent traversal, full path revision/support provenance, fail-closed component authorization, offline catalog graph publication, and an isolated Neo4j 5.15 Community service/test profile. The focused local mechanics gate passed `15` tests. Live Neo4j compatibility/isolation remains separately `not_run` in the implementation sandbox.

## Prompt 11 - deterministic query planner and explicit target semantics

Implemented without model inference, RL state, qrels, provider discovery, or query-derived authorization:

- `QueryPlan` records original/normalized query, deterministic language, task, exact keys, trusted authorized seed IDs, bounded alias candidates, requested target object types, reviewed graph pattern IDs, independent channel switches and validated request bounds;
- CTI identifiers are parsed before task planning. A pure identifier lookup reserves exact-hit priority by disabling lexical/dense/graph channels; a mapping request keeps the source identifier as evidence/seed rather than answer identity;
- missing graph seeds disable only graph traversal; lexical and dense channels remain independently enabled;
- ambiguous aliases remain bounded candidate IDs and never become exact identifiers;
- CTI task/target hints live in `CtiDomainAdapter`; report/synthesis/mapping conflicts resolve deterministically and query text cannot set principal, corpus, scope, raw filters, tool authority or Cypher;
- normal mapping selects `cti-catalog-mapping-2hop-v1`; only explicit `3-hop`/`three-hop`/`三跳` requests can select `cti-catalog-mapping-3hop-v1`, and the effective limit still respects the caller's lower hop cap;
- generic `TargetObjectRef` / `TargetProjection` keep evidence identity distinct from answer-object identity: object evidence targets the object, chunks target their parent object, and mapping paths require an explicit terminal object;
- mapping source seeds can remain cited evidence while being excluded from requested target ranking; requested target-type filtering is explicit;
- final target deduplication preserves first object occurrence and never invents object equivalence.

### Prompt 11 focused validation

Available sandbox: Python 3.13.5 compatibility workspace; repository target: Python 3.11.

```text
PYTHONPATH=. python -m pytest \
  tests/unit/retrieval/test_planner.py \
  tests/unit/retrieval/test_target_projection.py -q
18 passed
```

Combined Prompt 10/11 mechanics:

```text
PYTHONPATH=. python -m pytest \
  tests/unit/indexing/test_graph_projection.py \
  tests/unit/retrieval/test_graph_paths.py \
  tests/unit/retrieval/test_planner.py \
  tests/unit/retrieval/test_target_projection.py -q
33 passed
```

The modified P10/P11 modules also passed local `py_compile` in the compatibility workspace.

## Chained unresolved validation

`scripts/validate_advanced_04_11.py` is the new fail-fast Python 3.11 entry point. It deliberately chains the earlier correctness gates that had not yet been run on the exact later stack:

1. Prompt 04/05 CTI + durable-store tests;
2. existing Prompt 06/07 chained validator, including the reconciled current fixture ingestion E2E;
3. existing Prompt 08/09 chained validator;
4. Prompt 10/11 graph/planner tests;
5. `compileall` and `git diff --check`;
6. full repository pytest collection;
7. Compose parse when Docker exists;
8. optional real Neo4j integration when explicitly enabled and credentials are supplied.

The P08/09 validator was reconciled to provide validation-only Neo4j placeholder credentials during Compose parsing, because Prompt 10 correctly made those service variables mandatory.

The exact chain remains `not_run` in the implementation sandbox for a concrete prerequisite reason:

```text
Python 3.13.5
python3.11 unavailable
docker unavailable
```

The container also cannot clone the GitHub repository over the network, so a complete alternate Python 3.11 checkout could not be created here. No earlier partial-workspace result is relabeled as that exit gate.

## Still-unresolved operational/quality gates

- exact `python scripts/validate_advanced_04_11.py` on a complete Python 3.11 checkout;
- real Milvus 2.3.4 / PyMilvus 2.3.7 roundtrip and legacy endpoint isolation;
- real Neo4j 5.15 / neo4j-driver 5.15 roundtrip, advanced credential check and legacy endpoint isolation;
- authenticated restricted-evidence Milvus configuration;
- retrieval-quality/promotion thresholds.

## Handoff

Prompt 11 offline mechanics are implemented and stacked on the documented Prompt 10 handoff. A later correctness-dependent phase should first run `python scripts/validate_advanced_04_11.py` in the intended Python 3.11 environment. Live-service/deployment promotion remains separately blocked by the service gates above.