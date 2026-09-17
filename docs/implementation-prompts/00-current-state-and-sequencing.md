# Current state and sequencing handoff

Prompt 12 begins from Prompt 11 documented head `86593709fff8bab1b7b0153b1bad32f86ed3b651` on `feat/advanced-11-deterministic-query-planner` and is stacked on `feat/advanced-12-fusion-and-orchestration`.

Reconciliation notes:

1. Prompt 11 remains the deterministic planning and target-object authority. Prompt 12 consumes `QueryPlan`; it does not infer task/scope/policy from retrieval output.
2. Prompt 06 remains the active-generation authority. The orchestrator resolves trusted scope once and pins one snapshot for the whole request.
3. Channel outputs are already authorized `Candidate` objects inside `ChannelResult`. Fusion never hydrates denied backend records or bypasses per-channel scope/snapshot checks.
4. Fusion identity is `(evidence kind, immutable revision/reference)`: object uses its authorized revision view, chunk uses `chunk_uid`, and path uses `path_id`. Object/chunk/path evidence never merges across kinds.
5. Equal-weight RRF uses rank starting at 1 and `k=60`. A candidate may contribute once per channel; missing channels contribute zero; ties use stable fused candidate ID.
6. Pure entity lookup reserves exact-contributing candidates ahead of non-exact candidates. Mapping exact seeds do not gain an answer-priority tier.
7. Target-object ordering remains Prompt 11 first occurrence. Multiple chunks/paths referring to the same target do not have their retrieval scores summed into fabricated object corroboration.
8. Exact/lexical/dense are submitted concurrently under a bounded executor. Graph is not described as independent fan-out: it is eligible only after authorized deterministic exact seeds have been collected and the planner enables a reviewed graph pattern.
9. Default request/channel deadlines are 10s/3s. Each submitted channel receives the smaller remaining deadline. The executor bounds running+queued tasks; queue saturation is explicit rather than permitting timed-out work to accumulate.
10. Expected channel outage/timeout can yield a partial result. Unexpected catalog/policy exceptions are fatal and never cause legacy fallback.
11. Successful empty channels are preserved as `no_results`; failed/unavailable channels remain distinct. All-successful-empty yields `no_evidence`; all-unusable raises `RetrievalUnavailable`.
12. Authorized trace contains only channel/status/count/truncation. It omits evidence IDs/text and raw backend/provider error payloads.
13. `retrieve_candidates()` retains up to 60 fused candidates as the single pre-rerank boundary. Public `retrieve()` then applies request `top_k`. Prompt 13 should insert one optional final reranker between those two operations rather than reranking inside channels.
14. Local compatibility validation on Python 3.13.5 passed the Prompt 12 focused gate (`12 passed`) and `py_compile`. The required full Python 3.11 predecessor chain remains `not_run` because Python 3.11 and Docker are unavailable in this sandbox.
15. Legacy retriever/model routing, real-service compatibility/isolation, restricted-evidence authentication and quality gates remain unchanged and independent blockers.
