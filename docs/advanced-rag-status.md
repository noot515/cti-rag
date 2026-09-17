# Advanced RAG V3 implementation status

Updated: 2026-09-17. Prompt 11 documented head / Prompt 12 predecessor: `86593709fff8bab1b7b0153b1bad32f86ed3b651`. Current stacked branch: `feat/advanced-12-fusion-and-orchestration`. The legacy `packages/core/retriever.py`, legacy model router, legacy reranker, API/session/MQ behavior and legacy collections remain unchanged.

## Prompt 12 - independent channels, deterministic fusion and bounded degradation

Prompt 12 adds the advanced request-level orchestration boundary beside the legacy retriever:

- `packages/retrieval/fusion.py` implements equal-weight reciprocal-rank fusion with rank starting at 1 and `k=60`;
- candidate fusion identity is evidence kind plus immutable revision/reference identity, so object/chunk/path evidence is never coerced into one identity;
- a candidate contributes at most once per channel. Duplicate candidates/ranks and invalid/non-finite score state fail before ranking;
- absent channels contribute zero; stable ties use fused `candidate_id`;
- pure identifier lookup keeps candidates carrying an exact contribution in a reserved priority tier. Mapping queries do not receive that answer-priority tier merely because the source seed came from exact lookup;
- target-object ordering remains the Prompt 11 first-occurrence projection and is not synthesized by summing multiple chunks or paths;
- `AdvancedRetrievalOrchestrator` resolves trusted scope once and pins one active snapshot for the complete request;
- exact, lexical and dense channels are submitted concurrently under one hard-bounded executor; graph is submitted only after authorized deterministic exact seeds are available;
- each backend receives the smaller of the remaining request deadline and the nominal per-channel deadline. Default total/channel budgets are 10s/3s;
- bounded running+queued work prevents timed-out requests from accumulating an unbounded executor queue. Queue saturation is an explicit channel error;
- expected backend outage/timeout can degrade to a partial result while unexpected catalog/policy exceptions remain fatal and never fall back to the legacy retriever;
- successful empty channels are distinct from failed/unavailable channels. All-successful-empty produces `no_evidence`; no usable configured channel raises `RetrievalUnavailable`;
- request trace records only channel/status/count/truncation and deliberately omits denied IDs, evidence text and raw backend/provider errors;
- `retrieve_candidates()` retains up to 60 fused candidates as the pre-rerank boundary. Public `retrieve()` applies request `top_k`, leaving Prompt 13 a single well-defined final rerank insertion point.

No LLM, web search, hidden reranker, provider discovery or legacy fallback is introduced by Prompt 12.

### Prompt 12 focused validation

Available implementation sandbox: Python 3.13.5 compatibility workspace; repository target: Python 3.11.

```text
PYTHONPATH=. python -m pytest \
  tests/unit/retrieval/test_fusion.py \
  tests/unit/retrieval/test_orchestrator.py \
  tests/e2e/test_advanced_retrieval.py -q
12 passed
```

The new Prompt 12 modules also passed local `py_compile`.

The focused tests cover hand-computed RRF, per-channel duplicate rejection, absent-channel zero contribution, stable ties, exact lookup priority versus mapping semantics, deterministic repeat queries, timeout with a successful sibling, successful-empty versus unavailable, exact-seeded graph scheduling, bounded queue saturation, fatal unexpected policy/catalog exceptions, and five mechanics-only channel configurations without model or web access.

## Chained unresolved validation

`scripts/validate_advanced_04_11.py` remains the latest strict Python 3.11 predecessor chain. Prompt 13 will extend that chain through Prompts 12/13 so the earlier unresolved Python 3.11 gates are run before the new stages.

The exact predecessor chain remains `not_run` in this implementation sandbox for concrete prerequisites:

```text
Python 3.13.5
python3.11 unavailable
docker unavailable
```

The container also cannot resolve GitHub for a direct clone, so a separate complete Python 3.11 checkout cannot be constructed here. Local compatibility results are not relabeled as the required Python 3.11 exit gate.

## Still-unresolved operational/quality gates

- exact chained Prompt 04+ validation on a complete Python 3.11 checkout;
- full repository collection on the exact later stack;
- real Milvus 2.3.4 / PyMilvus 2.3.7 roundtrip and legacy endpoint isolation;
- real Neo4j 5.15 / neo4j-driver 5.15 roundtrip, credential checks and legacy endpoint isolation;
- authenticated restricted-evidence service configuration;
- retrieval-quality/promotion thresholds.

## Handoff

Prompt 12 offline correctness mechanics are implemented on top of Prompt 11. Prompt 13 may use `retrieve_candidates()` as the only pre-rerank boundary and must preserve the exact-lookup priority tier, Prompt 11 target semantics, policy authorization and pinned snapshot contract.