# Phase 06 implementation report — dense model representations and compatible retrieval

Status: **implementation/own deterministic gate passed; production dense acceptance remains blocked on actual embedding and real Milvus execution**

## Lineage and fingerprints

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/05-report.md`
- Validated Phase 06/07 code checkpoint: `ef78b24217b7aa56a2085a6da820528dfc622701`
- Config blob: `a90848b9f9884c344d3fe2cc10cd6ec8c13da591`
- Baseline corpus blob: `5820fa64bed3db3147d52d632975a21101893bff`
- Baseline model blob: `b06a0a7f5e5209553993045009c4e878b54a6435`
- Dense contracts blob: `86513fcca7f8a8d285cf112be450ed37d872d81a`
- Embedding runtime blob: `cb93991d1c0b1d315f7cc31bc733e155a421b3ba`
- Milvus adapter blob: `8e77215a66fdd911bb31c5c12fb67398166ad3ee`
- Exhaustive oracle blob: `e14f369c127e63200aa0bebe3ed41f3940346330`
- ANN evaluation blob: `00c54593f330832eda56ea51b110021e9201d6aa`
- Phase 06 test blob: `75845eb649351949a27132905b52e45776cc992b`
- Opt-in actual integration test blob: `818ec3ec0ef4f81d6c519d7f73b355dc2b4407a2`

## Implemented

### Explicit embedding-space identity

`EmbeddingFingerprint` records provider, model name/revision, tokenizer name/revision, dimension, pooling, normalization, distance metric, and deterministic context-prefix name/revision. Its canonical SHA-256 identity is used to separate representation/cache/collection generations.

A query embedding must carry the same fingerprint as the pinned dense generation. Mixed fingerprints, dimensions, or representation IDs are rejected instead of being searched in one vector space.

### Authorized bounded embedding runtime

`EmbeddingRuntime` provides:
- server-bounded queue size;
- batch-size limit;
- concurrency semaphore;
- bounded retry count;
- persistent SQLite embedding cache;
- security namespace in every cache key;
- full embedding fingerprint in every cache key;
- destination-policy authorization before provider-visible request text is assembled;
- vector dimension validation before cache/index admission.

Deterministic context prefixes are included in model input without replacing the original quotation text.

### Dense generation and deterministic identifiers

`DenseIndexer` derives representation identity from canonical passage UID + embedding fingerprint. The new Milvus adapter never uses the legacy random INT64 key scheme.

`MilvusDenseSearchPort` creates separate compatible collections keyed by full deterministic `passage_uid` VARCHAR primary keys. Collection names include embedding-fingerprint and generation identity. The existing `KnowledgeBase` implementation is unchanged.

### Filtered snapshot retrieval

Both the exhaustive oracle and Milvus adapter bind search to the dense generation referenced by the pinned snapshot. Scope and temporal filters include tenant, domain, access label, optional source IDs, current/historical availability, and the current revocation overlay.

Milvus ANN rows are not returned directly as citable evidence. They must rehydrate through the canonical EvidenceStore and match passage UID, revision, and locator. Canonical passage text/provenance replaces potentially stale index payload text.

### ANN evaluation contract

`evaluate_ann_against_exhaustive` computes the exhaustive oracle from the exact same snapshot-selected and authorized eligible set used by the dense request, then measures ANN recall@k against that set. Broad and selective-scope fixtures exercise the contract offline. Real Milvus recall remains a separate required gate.

### Lexical independence

No candidate-local BM25 behavior was promoted. Lexical and dense remain independent SearchPorts and merge only by citable passage identity, preserving each channel's raw score, direction, rank, and backend metadata.

## Validation actually executed

GitHub Actions run `35783030376`, job `106932955092`, Python 3.13.15:

```text
python -m unittest tests.contracts_phase1_test tests.validation_runner_test tests.ports_policy_phase2_test tests.canonical_ingestion_phase3_test tests.snapshot_publication_phase4_test tests.exact_lexical_phase5_test tests.dense_phase6_test tests.query_dag_fusion_phase7_test -v
```

Final cumulative result: **81/81 passed in 1.978 s**.

Phase 06 gate: **11/11 passed**, covering:
- embedding-fingerprint cache partitioning;
- authorization before remote text transfer;
- bounded batches/retry;
- bounded queue rejection before model call;
- prefix/original-text separation;
- snapshot scope/time/revocation filtering;
- query/generation fingerprint compatibility;
- ANN-vs-exhaustive broad/selective eligible-set measurement;
- lexical+dense merge by passage identity;
- fingerprint-separated Milvus collection identity;
- canonical hydration replacing stale index text.

## Explicit blocked external gates

1. `phase6-actual-embedding-model` — no pinned actual embedding model/runtime was available in offline CI. Deterministic embeddings are mechanics-only.
2. `phase6-milvus-real-lifecycle` — no reachable compatible Milvus service was available for actual create/index/publish/search/delete/restart persistence and ANN recall measurement.
3. Cumulative promotion also remains blocked by inherited Phase 0 gates and the real MySQL FULLTEXT gate.

Opt-in tests exist in `tests/actual_dense_integrations_phase6_test.py`; they do not silently skip into a passing required gate.

## Migration and rollback

No legacy Milvus collection was rewritten, deleted, or migrated. The new adapter is additive and not wired to the active legacy API path. Rollback is commit reversal plus cleanup of any future unpublished compatible generation. The new retrieval route remains disabled.
