# Phase 16 implementation report — cross-domain subquestions and typed joins

Status: **own deterministic gate passed; cumulative acceptance remains blocked by missing Phase 14 and inherited external gates**

## Lineage and fingerprints

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent implemented report: `docs/implementation/15-report.md`
- Phase 14 prerequisite: **not present / blocked**
- Validated Phase 15/16 code checkpoint: `595a48eda8b55ea3870ec6a8ab8391f64160853c`
- Planning models / JOIN operation: `10752dfa13b14e2ad2539f56f0a74a397257d2ab`
- Query executor: `95f9e8f4825179a4319f6b82beba6f2a566d7924`
- Passage fusion: `407cb41835e8269b10e0857b02aecab6ea6531c7`
- Typed cross-domain runtime: `f2560ec12f51824cf00a580a9c03f3c1df3cbc4f`
- Incident fixture/templates: `94b3d266028b50627c9179484a937fbc688ad3c1`
- Context response models: `9d1a3cf49e0c277ea240a412849753eba95f2023`
- Context packer: `4d9f8550f6b7467db99ad1936ddaa0555143a347`
- Advanced retrieval / obligation coverage: `22423464b4ef263bafb996b7a0441b3e75def66f`
- Phase 16 test blob: `f4c9e805bcad28ad574acd655cdb0fe7a4e02799`
- Validation registry: `ec3185e687675ebc1b262b4e16e3207daeea790d`
- Workflow: `67aaba40cd907bce604d79d2b20289ded020ac22`
- Config fingerprint: `a90848b9f9884c344d3fe2cc10cd6ec8c13da591`
- Model fingerprint: **none; Phase 16 deterministic gates invoke no model**

## Implemented

### Generic JOIN DAG operation

`PlanOperation.JOIN` is a first-class typed operation. `PlanNode` can carry a server-approved template ID and typed constraints. Existing operations remain unchanged.

Exact DAG nodes may additionally pin namespace/object type. This closed a real ambiguity found during validation: the 10-digit issuer CIK also matched the generic ISBN grammar when the executor ignored typed exact constraints.

### Typed keys and source-backed join records

A `TypedEntityKey` contains exactly:
`(namespace, entity_type, canonical identifier)`.

A `TypedJoinRecord` adds:
- relation type;
- source ID;
- provenance support;
- evidence kind;
- source availability;
- valid interval;
- tenant/access/processing labels;
- source domains;
- optional system-manifest identity.

There is no display-name join path.

When the reference join port is bound to the snapshot catalog/evidence store, all supporting revision UIDs must occur in the pinned manifest, remain unrevoked, and resolve to evidence before a record is eligible.

### Explicit unresolved states

A join result is one of:
- `resolved`;
- `ambiguous`;
- `missing`;
- `time_incompatible`;
- `suggestion_only`;
- `rejected`.

Only `resolved` can satisfy a dependent graph/calculation node. The executor rejects a dependent node before backend execution when its typed join dependency is unresolved.

Graph suggestions are returned separately and never promoted into a confirmed selected key.

### Joined graph and verified calculation adapters

`JoinedGraphPort` seeds the existing bounded GraphPort only from a resolved typed key.

`JoinedCalculationPort` invokes registered verified calculations only after a resolved join. The Phase 16 fixture reuses the Phase 13 `QuantCalculationEngine` and its point-in-time event study; no incident-specific arithmetic was placed in fusion.

### Incident/network/abnormal-return E2E fixture

The deterministic template decomposes into three subquestions:
1. incident/legal entity;
2. network infrastructure/route observation;
3. historical security + abnormal-return statistic.

Its required nodes are:
- exact CIK;
- lexical incident disclosure;
- issuer→network typed join;
- issuer→security typed join;
- joined BGP graph traversal;
- joined point-in-time event study.

The test uses actual repository components:
- canonical ingestion/object metadata;
- persistent exact index;
- SQLite FTS5 lexical index;
- reference GraphPort with source-backed BGP assertions;
- DuckDB structured finance tables;
- Phase 13 event-study calculator.

The complete fixture returns the independently specified numeric ground truth:
- alpha = 0;
- beta = 2;
- cumulative abnormal return = **3%**.

That structured output retains its existing association-only label and is not described as causation or profitability.

### Negative variants

The same generic template is exercised with:
- two eligible security mappings → `ambiguous`, no arbitrary selected security, calculation blocked;
- network relation outside event validity → `time_incompatible`, graph traversal blocked;
- a valid security identity with no price rows → join resolves but numeric obligation is `missing`;
- required incident disclosure source removed → overall outcome changes from complete to partial.

A graph-suggested prefix is present alongside the confirmed prefix and remains a suggestion rather than replacing the source-backed selection.

### Global budgets and fair packing

The cross-domain plan is rejected by the existing plan validator if six required nodes are placed under a five-call backend budget.

Passage fusion/context packing preserves subquestion coverage. A deliberately large-domain candidate pool cannot consume the entire token budget before a required small-domain passage is packed.

### Obligation coverage and replay

Every plan obligation receives:
- obligation ID/kind/subquestion;
- required flag;
- satisfied/partial/missing/failed status;
- citation count;
- reason.

The cross-domain coordinator returns coverage and unresolved joins. The general advanced evidence service also now includes this coverage and converts unsatisfied required obligations into explicit gaps.

Replay traces retain:
- plan ID/configuration hash;
- snapshot manifest;
- node operation/status;
- typed join decisions;
- structured calculation result UID;
- calculation input manifest/version/revision UIDs.

Typed joins, graph paths and structured calculations remain outside passage RRF.

## Validation actually executed

GitHub Actions run `35861752271`, job `107183398771`, Python 3.13.15:

- cumulative deterministic Phase 01–13 + 15–16 suite: **140/140 passed in 11.040 s**
- Phase 16 cross-domain gate: **7/7 passed in 1.669 s**
- affected legacy API/runtime regressions: **8/8 passed**
- fail-closed registry audit through Phase 16: **passed**; registry overall status remains `fail` because required blocked gates are present.

Phase 16 verifies:
- complete query spans quant + networking and exact + lexical + graph + structured evidence with citations/lineage at every obligation;
- ambiguous typed joins return partial coverage and never execute the dependent calculation;
- time-incompatible joins cannot bridge into graph traversal;
- missing price evidence is different from missing identity;
- removing a required supporting source changes completeness;
- an oversized global backend-call plan is rejected before execution;
- context packing preserves the smaller required subquestion despite a larger competing passage pool;
- the event-study fixture reproduces CAR = 3%;
- output explicitly avoids a causal/profitability interpretation.

## Explicit blockers

`phase14-required-prerequisite` remains **blocked**. Phase 16 is not promoted as cumulatively accepted over a missing prerequisite.

All prior live source/service/model gates—including live cyber/network/SEC/FRED, market-data entitlement, actual embedding/Milvus/reranker/tokenizer, Neo4j restart, and Phase 15 live humanities lifecycle—remain required blockers.

## Migration and rollback

Cross-domain composition is additive and uses registered typed templates. No special-case incident logic was added to passage fusion. Existing single-domain exact/lexical/graph/structured behavior remains available. Advanced retrieval remains disabled by default. Rollback removes the JOIN/templates/coverage layer without mutating canonical source evidence.
