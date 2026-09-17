# Current state and sequencing handoff

Prompt 13 begins from Prompt 12 documented head `358be5665a6d124bad5c5f01c794fe898ff30afb` on `feat/advanced-12-fusion-and-orchestration` and is stacked on `feat/advanced-13-single-final-reranker`.

Reconciliation notes:

1. Prompt 12 remains the request-scoped fusion/orchestration authority. Prompt 13 does not rerank inside exact, lexical, dense or graph channels.
2. The only rerank insertion point is after `retrieve_candidates()` returns its fused pre-rerank list and before public `retrieve()` applies request `top_k`.
3. At most 60 unique fused candidates are sent to the provider in one logical invocation. Any tail is preserved in original order and recorded separately.
4. Provider provenance is explicit through `RerankResult(status, model_fingerprint, scores_by_candidate_id, reason)`. Equal scores are valid success and are never used as a heuristic for provider failure.
5. Indexed provider adapters must validate strict integer indices, exact count, range, uniqueness, exhaustiveness and finite scores before mapping indices to candidate IDs. There is no missing-index zero fill.
6. A successful direct candidate-ID result must cover exactly the requested ID set and match the configured provider fingerprint.
7. The final stage uses `min(request_deadline, now + 4s)` and therefore cannot extend Prompt 12's total request deadline.
8. Optional timeout/provider failure/invalid result preserves the complete pre-rerank ordering and exposes `reranker=status=unavailable`. A required reranker raises `RequiredRerankerUnavailable` rather than silently degrading.
9. Stable equal-score ties retain the prior fused order. Prompt 12's pure exact-lookup priority IDs remain in the reserved priority tier even if a non-exact item has a larger reranker score.
10. Prompt 11 target semantics are unchanged by reranking. Reranking changes evidence candidate order only; it does not synthesize target-object corroboration or equivalence.
11. The deterministic payload contract uses Unicode codepoints (`unicode-codepoint-v1`), head truncation, query limit 8192, per-document limit 12000, total-document limit 720000 and maximum 60 documents.
12. Query destination and evidence are reauthorized immediately before provider egress. `StrictRerankEgressGuard` authorizes every resolver-supplied view with `authorize_evidence_set`; path resolvers must supply all node, assertion and support evidence views.
13. A revocation/policy denial during final materialization occurs before the provider call. Even if earlier candidates have been materialized locally, no partial provider batch is transmitted.
14. `scripts/validate_advanced_04_13.py` is now the strict correctness handoff. It first invokes the existing unresolved Prompt 04-11 Python 3.11 chain, then Prompt 12/13 focused tests, compile/whitespace and a final full-repository collection gate.
15. Local compatibility results on Python 3.13.5: Prompt 12 `12 passed`; Prompt 13 `15 passed`; combined Prompt 12/13 `27 passed`; modified modules compile. Python 3.11 and Docker remain unavailable here, so the exact chained gate and inherited live-service gates remain `not_run` rather than inferred.
16. Legacy reranker/model providers and `packages/core/retriever.py` remain unchanged. No production reranker provider, generative summarizer, quality-promotion claim or score-to-truth interpretation is introduced in Prompt 13.
