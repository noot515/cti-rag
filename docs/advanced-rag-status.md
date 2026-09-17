# Advanced RAG V3 implementation status

Updated: 2026-09-17. Reviewed application baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`. Prompt 02/03 head: `d210c0fde63df3ed765e0310f699f913722947d4`. Prompt 04 documented head: `19f7e6fe86fd6e3eb5b61cb6ece9d44143482bac`. Prompt 05 documented head / Prompt 06 predecessor: `ea127277f4fdade1aa66ee21d0ad37bc78f7d3c3`. Prompt 06 implementation code head before docs: `38afbfdb08356fcb279d0bb855bcff471cb0af09`. Current stacked branch: `feat/advanced-06-snapshot-publication`. Legacy retrieval remains available and the advanced path remains disabled by default.

## P00-P05 predecessor state

The predecessor stack provides offline-safe configuration/import behavior, reproducible L0 evaluation, generic evidence/provenance/policy contracts, hardened CTI normalization, and a durable scope-qualified SQLite evidence catalog with inactive snapshots. P00-P03 were separately validated on Windows/Python 3.11. Prompt 04/05 exact-stack Python 3.11/full-repository gates remain separately `not_run`.

## Prompt 06 - atomic generation publication and snapshot pinning

Implemented beside the legacy path:

- immutable `GenerationManifest`, `GenerationMember`, `ProjectionSpec`, `ProjectionReceipt`, and `ProjectionWriter` contracts;
- deterministic generation, manifest and membership hashes over exact revision membership and projection fingerprints;
- publication-specific versioned schema applied only when `SnapshotCatalog` is explicitly constructed, preserving Prompt 05 store behavior for non-publication callers;
- durable generation manifests, publication jobs, per-backend projection jobs/receipts, and a unique active pointer per `(domain, scope_id, corpus_id)`;
- jobs are persisted before projection writers run;
- readiness requires every enabled projection receipt to match generation/domain/scope/corpus, manifest hash, membership hash/count, fingerprint and visibility sentinel; verified receipts are immutable;
- generation states follow `building -> ready -> active` or `failed`; a failed required projection leaves the new generation inactive and retains the old pointer;
- activation switches the pointer and snapshot flags in one SQLite transaction, while job acknowledgement remains separately recoverable;
- `SnapshotHandle` pins one generation for request lifetime; an already-pinned reader remains on the old generation after a newer generation activates;
- prior generations remain stored/readable and are never repurposed or dropped by publication;
- revocation/deletion is checked as a live overlay, so withdrawn evidence is denied even through an older pin;
- restart recovery covers all-receipt-before-ready, ready-before-activation, and activation-before-job-ack crash windows; a partial receipt set remains inactive;
- import safety remains offline and does not initialize legacy MySQL/SQLAlchemy/Milvus paths.

Prompt 06 uses explicit fake projection writers for mechanics tests. It does **not** claim distributed transactions or atomicity across real Milvus/Neo4j/other services.

## Prompt 06 validation

Available sandbox interpreter: Python 3.13.5 with Pydantic 2.13.4. Repository runtime target remains Python 3.11.

```text
PYTHONPATH=. python -m pytest tests/unit/indexing/test_publication.py tests/unit/indexing/test_publication_recovery.py -q
14 passed

PYTHONPATH=. python -m compileall -q packages benchmark tests
passed
```

The exact Prompt 06 stack has not been rerun under Python 3.11 or through full repository collection. Those gates are `not_run`. Real Milvus/Neo4j/OpenCTI/model/service publication tests and retrieval-quality gates are also `not_run`; no service deployment or promotion is authorized by the sandbox mechanics result.

## Next-phase readiness

Prompt 07 may use the verified publication contract for local exact/lexical projection mechanics. The unresolved exact Python 3.11/full-checkout and real-service gates continue to block service promotion; they are not treated as passed by proceeding with isolated later-phase implementation.
