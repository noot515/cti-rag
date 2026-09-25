# Phase 07 implementation report — bounded query DAG and grouped fusion

Status: **implementation/own deterministic gate passed; cumulative promotion remains fail-closed on external service/model gates**

## Lineage and fingerprints

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/06-report.md`
- Validated Phase 06/07 code checkpoint: `ef78b24217b7aa56a2085a6da820528dfc622701`
- Query-plan contracts blob: `7caaa6791ebb181a28ad3e974033f13682b4e026`
- Deterministic compiler blob: `eb5860fcc3852ab3f2298726446c0776cd259b03`
- DAG executor blob: `c142502f565f4d8f07cff030c44b4bb0013a22bb`
- Fusion blob: `900c9386dccc6ffe8cccb7506a69d17f8a29fb3b`
- B1/B2/B3 fixture accounting blob: `e0c434275455ec4412eeeb663e6e3b39a40cad37`
- Phase 07 test blob: `c079d5d410725c972ec786cf6389f16932203257`

## Implemented

### Deterministic-first planning

The planner extracts canonical identifiers, date tokens, and declared units before any optional semantic decomposition. Server budgets clamp client-requested deadline, backend-call count, expansion rounds, total candidates, rerank candidates, and context tokens.

Task templates currently route:
- exact identifier-only queries to exact lookup without a planner-model call;
- numerical intent to structured execution when installed, otherwise an explicit required gap;
- relation intent to graph execution when installed, otherwise an explicit gap;
- explanatory evidence to independent lexical + dense channels;
- cross-domain evidence to domain-scoped subquestions;
- low-confidence domain routing to at most two already-authorized fallback domains.

Every plan carries the immutable effective scope, pinned snapshot reference, temporal request, evidence obligations, typed nodes, dependencies, subquestions, gaps, and configuration hash.

### Static plan validation

Plans fail before execution if they contain:
- duplicate node IDs;
- unknown dependencies;
- dependency cycles;
- unauthorized domains;
- too many backend calls;
- total candidate overspend.

The planner cannot create access rights or budget by model suggestion.

### Bounded DAG execution

Ready independent nodes execute concurrently under a server concurrency bound. Dependency nodes execute only after predecessors complete. A single absolute server deadline is propagated to search requests. Timeout remains `timeout`, not `empty`.

Cancellation propagates to in-flight cooperative tasks, and the cancelled aggregate future is explicitly consumed so cancellation completes cleanly without orphan-future warnings.

Unsupported/unavailable/rejected/timeout channels become explicit typed gaps instead of silently disappearing.

### Grouped RRF

Passage evidence uses equal-weight reciprocal-rank fusion with default `k=60` and 1-based ranks.

The implementation:
1. deduplicates identical query variants by `variant_key`;
2. combines unique variants within each channel with normalization so more rewrites cannot manufacture more channel weight;
3. fuses channel rankings equally;
4. uses stable passage UID tie-breaking;
5. merges duplicate lexical+dense hits by citable passage identity while preserving raw channel scores/ranks;
6. round-robins the final selection across subquestions so a large sub-corpus cannot erase another subquestion's evidence.

Exact and structured obligations are retained separately from passage competition. A semantically similar wrong-ID passage therefore cannot satisfy or replace the exact obligation.

### Minimal B1/B2/B3 fixture

The benchmark accounting layer records B1 exact, B2 lexical, and B3 grouped-fusion MRR/recall under the same scope hash and snapshot ID. Synthetic/fake dense results explicitly carry `semantic_quality_claim=false`; this benchmark proves pipeline comparability mechanics, not model-quality superiority.

## Validation actually executed

GitHub Actions run `35783030376`, job `106932955092`, Python 3.13.15.

Final cumulative result: **81/81 passed in 1.978 s**.

Phase 07 gate: **15/15 passed**, covering:
- exact-ID route with zero planner-model calls;
- deterministic identifier/date/unit extraction;
- cross-domain subquestion generation;
- cycle rejection;
- candidate-budget rejection;
- authorized-only fallback domains;
- explicit graph/structured gaps;
- concurrent lexical+dense nodes;
- dependency ordering;
- clean in-flight cancellation;
- timeout distinct from empty;
- fixed-rank RRF formula;
- cross-subquestion result coverage;
- duplicate rewrite non-amplification;
- exact obligation protected from high-similarity wrong-ID passage;
- B1/B2/B3 scope/snapshot comparability.

## Limitations and next boundary

The optional semantic planner is intentionally not needed by the validated deterministic cases and has no authority to expand scope or budgets. Graph and structured execution are capability hooks; Phase 07 does not pretend those backends are implemented by these prompts.

No new public API route was activated. The next phase can compose these planner/fusion contracts into the advanced-retrieval API and evidence-envelope layer, while promotion remains blocked until all inherited and Phase 06 external gates are actually executed.
