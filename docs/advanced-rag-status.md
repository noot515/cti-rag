# Advanced RAG V3 implementation status

Updated: 2026-09-17. Reviewed application baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`. Prompt 05 documented head: `ea127277f4fdade1aa66ee21d0ad37bc78f7d3c3`. Prompt 06 final documented head / Prompt 07 predecessor: `fb9a816ac083741fcce245c4e0b02fbd001e7c6e`. Prompt 07 implementation/hardening head before this documentation commit: `d59673c2fea84373d46b706a6786ea39d9bbe778`. Current stacked branch: `feat/advanced-07-chunk-exact-lexical`. Legacy retrieval remains available and the advanced path remains disabled by default.

## Prompt 06 - atomic generation publication and snapshot pinning

Prompt 06 implements immutable generation manifests and projection receipts, durable publication/projection jobs, fake-backend visibility verification, `building -> ready -> active` publication state, an atomic catalog active pointer, request-lifetime `SnapshotHandle` pinning, live revocation/deletion overlays, and restart recovery for receipt/ready/activation crash windows. It reuses Prompt 05 snapshot membership rather than creating a second evidence catalog. Publication mechanics are trusted-code-only and preserve the legacy collection path.

Prompt 06 uses explicit fake projection writers for mechanics tests. It does **not** claim distributed transactions or atomicity across real Milvus, Neo4j, OpenCTI, or other external services.

## Prompt 07 - deterministic chunks, exact lookup and persistent full-corpus BM25

Implemented beside the legacy retriever without modifying the protected legacy indexing/BM25 path:

- deterministic field-aware chunking with a pinned regex/unicode tokenizer, 450-token target, 75-token overlap, stable section order, whole CTI identifiers, content hashes, tokenizer/chunker fingerprints, and source-field character-offset metadata;
- small objects stay intact when the emitted representation fits the budget; long prose uses deterministic overlapping windows;
- CTI chunks inherit object policy metadata plus effective marking references/granular selectors/citation locator;
- persistent exact indexes are generation-scoped validated JSON artifacts built only from canonical external identifiers, source identities and STIX IDs; aliases and body mentions never become exact identity;
- exact lookup returns object-revision `BackendHit` records pinned to a `ResolvedScope` and `SnapshotRef`; unknown identifiers are successful misses;
- persistent lexical indexes cover the complete generation chunk corpus, storing validated tokenization, document lengths, document frequencies, average length and declared BM25 `k1=1.5`, `b=0.75` parameters;
- lexical indexes reopen from validated JSON without refitting per query, use deterministic score ties, return chunk-revision hits, and exclude zero-score nonmatches;
- text hydration rechecks pinned generation membership, live tombstone/revocation state and retrieval policy authorization before returning chunk text;
- exact and lexical projection writers produce Prompt 06 receipts only after reopening and verifying persisted artifacts. Receipt verification includes manifest/membership/fingerprint/artifact hash and visibility sentinel checks; a corrupted artifact cannot activate a generation;
- fixture configuration enables exact/lexical only and records dense/graph as not configured with outbound networking disabled;
- `python -m packages.indexing.cli ingest --config ... --manifest ...` validates the trusted fixture manifest and object-file hash, keeps corpus/evaluation roles separate, constructs a trusted fixture principal/source allowlist, normalizes, chunks, persists, builds both projections and atomically publishes the generation;
- repeated no-change fixture ingest is designed to preserve the generation ID and produce zero logical catalog changes; changed object revisions produce new chunk membership rather than reusing stale chunks;
- no pickle, model call, download, web request, dense search or graph search is introduced by this phase.

The additional `scripts/validate_advanced_06_07.py` file exists because the implementation session explicitly requested one fail-fast chained validation entry point. It requires Python 3.11, verifies the Prompt 06 head is an ancestor, runs P06 and P07 tests in one pytest invocation, runs fixture CLI ingestion in a temporary state directory, then runs `compileall` and `git diff --check`.

## Validation state

Repository runtime target: Python 3.11. Available implementation sandbox: Python 3.13.5 and a partial scratch workspace, not a complete repository checkout.

Prompt 06 authoritative focused result from its branch:

```text
PYTHONPATH=. python -m pytest tests/unit/indexing/test_publication.py tests/unit/indexing/test_publication_recovery.py -q
14 passed

PYTHONPATH=. python -m compileall -q packages benchmark tests
passed
```

Prompt 07 local contract/integration harness after reconciling to the actual Prompt 06 `GenerationManifest`/`ProjectionReceipt` shape:

```text
PYTHONPATH=. python local_validate_p07.py
LOCAL_P07_INTEGRATION_OK 1 1 1

python -m py_compile packages/indexing/chunker.py packages/indexing/lexical_indexer.py packages/indexing/cli.py packages/retrieval/exact.py packages/retrieval/lexical.py tests/unit/indexing/test_chunker.py tests/unit/retrieval/test_exact.py tests/unit/retrieval/test_lexical.py tests/e2e/test_fixture_ingestion.py
passed
```

The exact chained Prompt 06/07 validator is intentionally **not run** in this sandbox because it requires Python 3.11. The observed prerequisite failure is:

```text
python scripts/validate_advanced_06_07.py
Prompt 06/07 validation requires Python 3.11; observed 3.13.5
```

An attempt to run the full Prompt 07 pytest files in the partial scratch workspace cannot collect because that scratch workspace does not contain the repository's `packages.domains` tree. That is recorded as an incomplete-checkout limitation, not as a passing or failing repository correctness result. Therefore the exact P07 full-checkout pytest gate, exact Python 3.11 chained gate, full repository collection, real-service compatibility and retrieval-quality gates remain `not_run`.

## Next-phase readiness

Prompt 07 code is implemented and stacked on the verified Prompt 06 publication contract. Before treating Prompt 07 as a completed correctness gate or starting a dependent phase, run `python scripts/validate_advanced_06_07.py` from a clean/full checkout with the isolated Python 3.11 advanced environment. Real-service deployment/promotion remains blocked regardless of the offline mechanics result.
