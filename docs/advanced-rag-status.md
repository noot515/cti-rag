# Advanced RAG V3 implementation status

Updated: 2026-09-17. Prompt 12 documented head / Prompt 13 predecessor: `358be5665a6d124bad5c5f01c794fe898ff30afb`. Current stacked branch: `feat/advanced-13-single-final-reranker`. The legacy `packages/core/retriever.py`, legacy model router/reranker, API/session/MQ behavior and legacy collections remain unchanged.

## Prompt 12 - independent channels, deterministic fusion and bounded degradation

Prompt 12 adds a separate advanced request-level orchestration boundary:

- equal-weight reciprocal-rank fusion with rank starting at 1 and `k=60`;
- evidence identity is kind plus immutable revision/reference, so object/chunk/path candidates remain distinct;
- one contribution per candidate per channel, absent channels contribute zero, invalid/non-finite contributions fail before ranking, and stable ties use fused candidate ID;
- pure identifier lookup preserves an exact-match priority tier; mapping seeds do not become answer-priority merely because exact lookup supplied them;
- scope resolves once and one active snapshot is pinned for the request;
- exact/lexical/dense are submitted concurrently under a hard-bounded executor; graph waits for authorized deterministic exact seeds;
- default total/channel budgets are 10s/3s and each backend receives the smaller remaining deadline;
- queue saturation, timeout, successful-empty and unavailable/error are explicit states;
- expected channel outage may yield partial evidence while unexpected catalog/policy failures remain fatal with no legacy fallback;
- trace contains only channel/status/count/truncation and omits evidence IDs/text and raw provider/backend payloads;
- `retrieve_candidates()` retains at most 60 fused candidates as the single pre-rerank boundary.

Prompt 12 focused compatibility gate:

```text
PYTHONPATH=. python -m pytest \
  tests/unit/retrieval/test_fusion.py \
  tests/unit/retrieval/test_orchestrator.py \
  tests/e2e/test_advanced_retrieval.py -q
12 passed
```

## Prompt 13 - one final reranking stage with complete validation

Prompt 13 inserts exactly one optional final reranking stage after Prompt 12 fusion and before final `top_k` truncation:

- `RerankResult` preserves explicit provider status, model fingerprint, candidate-ID scores and failure reason; equal scores alone are never interpreted as provider failure;
- indexed-provider output is accepted only when indices are strict integers, in range, unique, exhaustive and mapped one-to-one to the requested IDs; missing/defaulted indices are never zero-filled;
- every successful score must be finite and every requested candidate ID must be covered exactly once;
- up to 60 unique fused candidates are reranked in one logical provider invocation. The non-reranked tail remains in its original order and is recorded separately;
- the stage deadline is the smaller of the request's remaining total deadline and the nominal 4-second rerank budget;
- optional timeout/provider failure/invalid response returns `reranker_unavailable` semantics and restores the complete pre-rerank order; a configured required reranker raises `RequiredRerankerUnavailable` instead of silently succeeding;
- stable equal-score ties retain prior fused rank;
- Prompt 12's exact lookup priority tier remains ahead of non-exact evidence even when a non-exact candidate receives a larger reranker score;
- deterministic payload contract is `unicode-codepoint-v1` with head truncation, 8192 query codepoints, 12000 per document, 720000 total document codepoints and at most 60 candidates;
- query destination and every evidence component are reauthorized immediately before payload construction. `StrictRerankEgressGuard` uses a resolver bundle plus `authorize_evidence_set`; path resolvers are required to return node, assertion and support views;
- revocation/policy denial during this final egress gate aborts before any provider call, so forbidden text is not transmitted;
- the advanced orchestrator records actual reranker status and provider fingerprint, and applies request `top_k` only after reranking/fallback.

Prompt 13 focused compatibility gate:

```text
PYTHONPATH=. python -m pytest \
  tests/unit/retrieval/test_reranker_contract.py \
  tests/unit/retrieval/test_reranker_egress.py -q
15 passed
```

Combined Prompt 12/13 mechanics:

```text
PYTHONPATH=. python -m pytest \
  tests/unit/retrieval/test_fusion.py \
  tests/unit/retrieval/test_orchestrator.py \
  tests/e2e/test_advanced_retrieval.py \
  tests/unit/retrieval/test_reranker_contract.py \
  tests/unit/retrieval/test_reranker_egress.py -q
27 passed
```

`packages/retrieval/fusion.py`, `orchestrator.py` and `rerank.py` also passed local `py_compile`.

## Chained unresolved validation

`scripts/validate_advanced_04_13.py` is the strict Python 3.11 correctness handoff. It first runs the existing `scripts/validate_advanced_04_11.py` chain, then the Prompt 12/13 focused tests, compile/whitespace checks and a final full-repository collection at the Prompt 13 head.

The exact chain remains `not_run` in this implementation sandbox for concrete prerequisites:

```text
Python 3.13.5
python3.11 unavailable
docker unavailable
```

The container also cannot resolve GitHub for a direct clone. Local Python 3.13.5 compatibility results are therefore not relabeled as the required Python 3.11 exit gate.

## Still-unresolved operational/quality gates

- `python scripts/validate_advanced_04_13.py` on a complete Python 3.11 checkout;
- full repository collection on the exact Prompt 13 stack;
- real Milvus and Neo4j roundtrip/isolation gates inherited from prior phases;
- authenticated restricted-evidence service configuration;
- any real optional reranker provider/model compatibility test;
- retrieval-quality/promotion thresholds, including the later R5/R6 quality comparison.

## Handoff

Prompt 13 offline correctness mechanics are implemented on top of Prompt 12. A later phase may consume the post-rerank candidate order, but must not reinterpret retrieval/reranker scores as truth probabilities or bypass the existing policy/snapshot/target semantics.