# Phase 04 implementation report — coherent snapshot publication and immediate revocation

Status: **implementation/own gate passed; cumulative promotion remains blocked by inherited Phase 0 gates**

## Lineage and fingerprints

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/03-report.md`
- Phase 04/05 code checkpoint: `9c67c4012c4e8810ef4087d3eeb6b928f0b0165b`
- Config blob: `a90848b9f9884c344d3fe2cc10cd6ec8c13da591`
- Baseline corpus blob: `5820fa64bed3db3147d52d632975a21101893bff`
- Baseline model blob: `b06a0a7f5e5209553993045009c4e878b54a6435`
- Phase 04 test blob: `3389bc5ba947e10d8ad29f4383687df6f754123b`
- No model was invoked.

## Implemented

A backend-neutral `ProjectionBuilder` contract and immutable projection-generation model now record the exact evidence revision set, representation versions, checksum, readiness, serving visibility, referential-integrity result, quarantined count, supported query capabilities, creation time, and fixture citable payloads.

`SnapshotCatalogStore` persists staged generations, immutable manifests, one atomic `current` catalog pointer, reader leases, a current revocation overlay, cache-invalidation events, and projection cleanup tasks. A manifest can publish only when every required generation exists, is ready, is serving-visible, passes referential integrity, and all enabled generations bind to the identical sorted revision set. Graph or structured generations therefore cannot silently drift from exact/lexical/dense membership.

Requests can pin the current manifest through reader leases. Old generations remain protected while a lease is active; release or expiration allows cleanup once the generation is no longer the current generation. Failed staged generations can be cleaned without affecting the serving pointer. Rollback repoints the catalog only to a still-serviceable immutable manifest.

The revocation overlay is independent of the pinned manifest. Candidate admission, exact/lexical retrieval, and the revocation-aware evidence hydration wrapper consult current revocations, so an old snapshot cannot re-expose revoked evidence. Admission creates cache invalidation records plus cleanup tasks for exact, lexical, dense, graph, structured, and derived projections; each can be acknowledged independently.

Catalog fixture backup/restore serializes generations, manifests, the publication pointer, revocations, invalidations, and cleanup state. Restoring into a fresh catalog reproduces the manifest and citable generation payloads.

## Validation actually executed

GitHub Actions run `35740638328` on Python 3.13.15 compiled the side-effect-free runtime and all chained gate modules, then ran the cumulative Phase 01–05 deterministic suite.

```text
python -m unittest tests.contracts_phase1_test tests.validation_runner_test tests.ports_policy_phase2_test tests.canonical_ingestion_phase3_test tests.snapshot_publication_phase4_test tests.exact_lexical_phase5_test -v
```

Final result: **55/55 passed in 1.037 s**, including **10 Phase 04 snapshot/publication/revocation tests**.

Phase 04 acceptance fixtures passed:
- crash after staged projection work but before pointer swap leaves the previous manifest serving;
- a reader stays pinned to one coherent manifest across publication and prevents cleanup of its generations;
- missing serving visibility/referential integrity blocks publication;
- incompatible revision sets across projection kinds block publication;
- publication retry is idempotent;
- revocation immediately blocks response admission and canonical hydration even through an old pinned manifest;
- cache invalidation and cascading projection cleanup acknowledgments are explicit;
- failed-generation cleanup and expired-lease recovery behave deterministically;
- backup/restore reproduces manifest, projection generation payloads, and current revocation state;
- snapshot-required backends are rejected before invocation if a caller omits a pinned snapshot.

## Limitations, migration, and rollback

The publication catalog is validated with a persistent DB-API/SQLite fixture; live MySQL metadata deployment has not been exercised. No live projection alias/index/catalog pointer was changed. The legacy serving route remains untouched.

An earlier workflow attempt compiled every historical test file and failed on the pre-existing syntactically invalid `tests/test_ner.py`. The workflow now compiles the complete new runtime plus the six named chained gate modules and runs those gates explicitly; the unrelated legacy syntax defect is not reported as a pass.

Rollback is additive-file/commit reversal. No production generation or reader lease exists until an explicit composition root activates this runtime.
