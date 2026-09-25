# Phase 08 implementation report — reranking, context packing, and advanced evidence API

Status: **implementation/own deterministic gate passed; legacy API regression passed; production promotion blocked by cumulative external gates**

## Lineage and fingerprints

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/07-report.md`
- Validated Phase 08/09 code checkpoint: `6c0e5b0f53ddedf15b4da5f4bcbfb87d04fdbc6f`
- Config blob: `a90848b9f9884c344d3fe2cc10cd6ec8c13da591`
- Baseline corpus blob: `5820fa64bed3db3147d52d632975a21101893bff`
- Baseline model blob: `b06a0a7f5e5209553993045009c4e878b54a6435`
- Context contracts: `11e255f68b0073ddd860ab3a720907386a56972c`
- Reranker: `d0a24e8cf245fdf3ef213f220a2653b40cb51025`
- Context packer: `faafbb6e8280617423c8d9efa882658a6738a7d5`
- Citation verifier: `1506636fdbc095a3b3700b31d97335255eb2617c`
- Evidence hydrator: `0d69d509429121063d6a3cd073cbd96bbd5884f5`
- Trace capture: `ff212a348a4083d1fb05723a581922392a40f8da`
- Advanced service: `e39e6c2497590310a3710f599eccd230b9f5a20f`
- FastAPI router: `b6fd10839bee3990d220381f2e09e26603af7dd3`
- Phase 08 test blob: `ea827489822218ca54b845fe00602912da451b21`

## Implemented

The new application service now performs the complete evidence-only control flow: authenticated policy admission, compatible snapshot pinning, deterministic plan compilation, bounded DAG execution, grouped RRF, canonical evidence hydration, optional reranking, deterministic context packing, citation verification, final policy revalidation, typed status determination, safe diagnostics, and privacy-minimized trace capture.

The optional reranker is centrally owned. Candidate authorization and canonical revision/locator/text checks occur before provider-visible inputs are created. The provider receives only passage text; exact and structured evidence obligations remain typed and cannot be suppressed by text reranking. Deadline/candidate limits are enforced. Any reranker exception or policy denial degrades to fused order with an explicit reason rather than failing the request or widening exposure.

Context packing uses the injected target-tokenizer interface, reserves instruction/tool/output tokens, applies the server-bounded plan context limit, preserves subquestion coverage, penalizes redundant/same-origin evidence, and expands parents only through an expander that receives the immutable scope and pinned snapshot. Parent results are rechecked before packing. Truncated text is decoded on tokenizer boundaries and citations are resolved against canonical evidence after truncation. Typed exact/structured obligations are accounted before passage evidence.

`POST /research/advanced-retrieval` now has typed request/response models and returns `complete`, `partial`, `insufficient_evidence`, or `failed`. Missing evidence is distinct from backend failure. Diagnostics expose node/operation/status/reason-code only. Debug traces are emitted only when the effective policy grants `debug_traces_allowed`; traces contain a query digest rather than raw query content.

The endpoint is additive and evidence-only. It rejects answer-generation response modes and web overlay requests. Runtime construction is dependency-injected through `rag/api/advanced_runtime.py`; `CTI_RAG_ADVANCED_RETRIEVAL_ENABLED` defaults off. Existing chat/data routes are unchanged and continue to be tested.

A synthetic end-to-end fixture executes source ingestion → canonical normalized objects → exact/SQLite-FTS projections → coherent publication → advanced retrieval → canonical hydration → reranking → context packing/citation verification. A separate exact query proves exact obligations survive the text pipeline.

B4-vs-B3 accounting is present, but fixture/fake reranking is explicitly marked `semantic_quality_claim=false` and `real_model_status=not_run`.

## Validation actually executed

GitHub Actions run `35839225054`, job `107110015621`, Python 3.13.15:

- cumulative Phase 01–09 unittest suite: **98/98 passed in 4.228 s**
- Phase 08 own gate: **6/6 passed in 0.075 s**
- affected legacy API/runtime regression: **8/8 passed in 0.09 s**
- cumulative validation registry: expected overall `fail` because required external gates remain blocked; Phase 08 deterministic and legacy gates are `pass`.

Phase 08 fixtures verify:
- a spy reranker never receives denied candidate text;
- private parent expansion is never sent to the reranker and is excluded from packed evidence;
- reranker failure falls back to fused order with explicit degradation;
- target-tokenizer budgeting truncates deterministically and citation spans still verify;
- missing evidence serializes differently from backend failure;
- traces omit raw query text;
- B4-vs-B3 fake comparison is labeled non-semantic;
- actual synthetic ingestion/publish/retrieve/evidence-response flow works;
- exact obligations remain present;
- legacy chat/model-routing and Docker/runtime-requirements tests still pass.

## Explicit blocked gates

- `phase8-actual-reranker-model`: no pinned real reranker/model runtime was available in offline CI.
- `phase8-actual-generator-tokenizer`: the actual configured generator/tokenizer was not loaded in offline CI.
- inherited Phase 0, real MySQL, actual embedding-model, and real Milvus lifecycle gates remain blocked.

The new API remains disabled by default and therefore is not promoted to production serving in this phase.
