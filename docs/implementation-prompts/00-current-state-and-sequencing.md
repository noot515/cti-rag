# Current state and sequencing handoff

Prompt 08 begins from Prompt 07 documented head `ecc28482f57e93fa6d90cbf99f90146c762cd9fb` and is stacked on `feat/advanced-08-embedding-provider-contract`. Prompt 08 implementation code reached `14df9ae472fa0bb54e6e574ec02d100b05bb9d63` before this documentation commit.

Reconciliation notes:

1. The predecessor already had a compact provider fingerprint in `packages/evidence/config.py`; Prompt 08 extends it with metric, document/query instructions, tokenizer and optional artifact hash instead of introducing a competing configuration model.
2. The predecessor default embedding revision `v1` is preserved. Reproducibility is strengthened by hashing the complete provider fingerprint rather than changing a revision label without need.
3. Advanced provider contracts live in `packages/retrieval/providers.py`; they do not import `packages/models/embedding.py`, OpenAI/Zhipu/FlagEmbedding, requests, model artifacts or network clients at import time.
4. Provider selection is trusted and lazy. Missing real providers are unavailable errors; no same-dimension substitution or fixture fallback is allowed.
5. Document/query egress destinations are explicit. Authorization occurs before encoding, and invalid output ID mappings, non-finite values, dimensions or required normalization fail before persistence/search.
6. The deterministic fixture provider is stdlib-only and mechanics-only. Its fingerprint includes separate document/query instructions and a deterministic artifact hash; cross-process stability is covered by the focused tests.
7. `packages/retrieval/dense.py` is a local generation-scoped fixture projection, not the Milvus implementation. It persists numeric vectors as validated JSON, reopens against Prompt 06 generation membership, and enforces provider fingerprint, scope and snapshot identity.
8. Dense hits remain untrusted backend output until catalog membership, live lifecycle state and caller policy are checked during candidate construction.
9. The Prompt 07 fixture CLI is narrowly extended to register exact, lexical and dense writers in the same Prompt 06 publication transaction. Graph remains disabled; fixture networking/downloads/web remain forbidden.
10. `requirements-advanced-models.txt` deliberately adds no heavyweight dependency for fixture mechanics. Any future real provider must be explicitly selected, pinned and authorized rather than becoming an import-time dependency.
11. Legacy embedding implementations, aliases, collections and API/session behavior remain unchanged.
12. Focused Prompt 08 sandbox validation passed (`12 passed`) on Python 3.13.5. Exact Python 3.11 full-checkout and real-model gates remain `not_run`.
13. Prompt 09 may use the fingerprint-bound provider and Prompt 06 projection contract to build an isolated Milvus adapter. Real Milvus compatibility/legacy-isolation evidence remains an independent release gate.
