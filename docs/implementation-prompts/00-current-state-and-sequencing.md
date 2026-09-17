# Current state and sequencing handoff

Prompt 14 begins from Prompt 13 documented head `73a0429dc7de58714148197172f9fffb68baf052` on `feat/advanced-13-single-final-reranker` and is stacked on `feat/advanced-14-evidence-packing`.

Reconciliation notes:

1. Prompt 12 remains the request-scoped retrieval/fusion authority and Prompt 13 remains the only final reranking authority. Prompt 14 operates only after final candidate ordering and request `top_k` selection.
2. Evidence packing never uses legacy reranked strings. It resolves structured object/chunk/path evidence from the advanced catalog and the request-local pinned path set.
3. `CitationRef` contains stable evidence UID plus object/assertion revisions, domain/scope/snapshot, source locator/offset metadata and source URI when already present in the catalog. Response-local `CTI-NNN` labels are not global evidence identity.
4. `PackResult` separately reports citation validity (`validated`) and claim support (`not_assessed`); citation resolvability is not treated as entailment.
5. The exact context budget is `min(8000, model_window - system - history - query - output_reserve - safety_margin)` using the configured generator tokenizer. The fixture tokenizer is explicitly mechanics-only.
6. Labels, headers, separators and evidence body all count toward the validated budget. A nonpositive budget rejects the request; an oversized block is skipped rather than truncated.
7. Packing is bounded to at most 15 indivisible blocks. Soft per-object/source caps shape the first ranked pass but can be relaxed only after that pass; hard token/block budgets are never relaxed.
8. Paths remain atomic evidence bundles. Every pinned node revision, assertion revision and support UID must resolve, remain live and pass authorization before the path may render; otherwise the entire path is omitted.
9. Mapping/reference/assertion language remains explicit and assertion kind is retained. Contradictory evidence from distinct sources is kept rather than merged into fabricated consensus.
10. Evidence body text is explicitly rendered as quoted untrusted content. Packing performs no LLM call, web fetch, URL retrieval or tool execution.
11. Duplicate evidence is suppressed by stable kind/evidence/revision identity, but distinct contradictory evidence is not deduplicated merely because it names the same target object.
12. After provisional packing every accepted block is resolved/authorized again. Withdrawal, policy denial or any authoritative block change causes deterministic exclusion and a complete rebuild before response egress.
13. The public `RetrievalResult` receives only citations for emitted context. Richer response-local citation coordinates remain available through `PackResult.local_citation_map` while the response snapshot supplies the pinned snapshot identity.
14. Local Python 3.13.5 compatibility validation: Prompt 14 focused gate `10 passed`; combined Prompt 12/13/14 mechanics `42 passed`. These are not substitutes for the required Python 3.11 chain.
15. Prompt 15 must start from the final documented Prompt 14 SHA and introduce trusted API identity/server-owned corpus grants without trusting legacy `KnowledgeDatabase.user_id` or request-body ownership fields.
16. Exact Python 3.11, full collection, live Milvus/Neo4j isolation and quality/promotion gates remain independent unresolved gates; no offline result authorizes deployment.
