# Advanced RAG V3 implementation status

Updated: 2026-09-17. Prompt 07 documented head / Prompt 08 predecessor: `ecc28482f57e93fa6d90cbf99f90146c762cd9fb`. Prompt 08 implementation code head before this documentation commit: `14df9ae472fa0bb54e6e574ec02d100b05bb9d63`. Current stacked branch: `feat/advanced-08-embedding-provider-contract`. Legacy embedding providers and legacy retrieval remain untouched; the advanced path remains separate.

## Prompt 08 - fingerprint-bound embedding providers and deterministic fixture dense retrieval

Implemented beside the legacy model stack:

- import-inert `EmbeddingProvider` contract with explicit `encode_documents` and `encode_queries` operations, deadline/cancellation checks, and no implicit provider fallback;
- immutable embedding fingerprint covering provider, model, explicit revision, dimensions, metric, normalization, document/query instructions, tokenizer identity, optional artifact SHA-256, and remote/local status;
- strict typed ID-to-vector outputs with exact output-ID coverage, duplicate rejection, finite-vector checks, dimension checks, and L2-normalization validation before index writes or query use;
- same-dimension providers with different model/revision/instruction/tokenizer identity are not interchangeable; fingerprint mismatch requires reindexing;
- deterministic stdlib-only fixture embeddings for mechanics testing with stable cross-process vectors and a content-derived artifact identity. They are not a semantic-quality claim;
- trusted lazy `EmbeddingProviderRegistry`; an unavailable selected real provider raises instead of falling back to the fixture provider;
- destination authorization happens before encoding. The fixture provider permits only its explicit local destination allowlist and performs zero vector work after a denial;
- generation-scoped persistent dense JSON projection bound to the Prompt 06 manifest/membership and provider fingerprint, with reopen-time membership/vector/fingerprint validation and deterministic exact similarity ranking;
- dense query and candidate construction require matching `ResolvedScope`/`SnapshotRef`, recheck live deletion/revocation state, and authorize evidence before returning a trusted candidate;
- a Prompt 06-compatible `DenseProjectionWriter` reopens and verifies the persisted dense artifact before emitting a receipt;
- fixture ingestion now publishes exact, lexical, and deterministic dense projections together while remaining network/download/web disabled;
- real model SDKs remain optional and are not imported or installed for the fixture correctness path. Existing `packages/models/embedding.py` and legacy embedding aliases/provider behavior are unchanged.

Reconciliation: the predecessor advanced config already exposed a small provider fingerprint. Prompt 08 extends that record rather than replacing it, and keeps its existing default embedding revision `v1` stable while adding metric, instructions, tokenizer and artifact identity. The fixture CLI is narrowly updated because Prompt 08 requires the local dense writer to participate in fixture publication.

## Prompt 08 validation

Available implementation sandbox: Python 3.13.5. Repository target remains Python 3.11.

```text
PYTHONPATH=. python -m pytest tests/unit/retrieval/test_embedding_provider.py tests/unit/retrieval/test_fixture_dense.py -q
12 passed
```

The local compatibility pass also compiled the Prompt 08 modules/configuration and exercised deterministic reopen/ranking. Exact Python 3.11 full-checkout validation, the earlier Prompt 06/07 chained Python 3.11 gate, full-repository collection, optional real-model/provider tests, and retrieval-quality gates remain `not_run`; they are not inherited from predecessor results.

## Next-phase readiness

Prompt 09 may build an isolated Milvus projection against this fingerprint/provider contract. Fake-client Milvus mechanics may proceed offline. Real Milvus client/server compatibility and legacy-access isolation remain separate release gates and must be reported as pass/fail/not_run rather than inferred from unit tests.
