# Phase 03 implementation report — canonical storage and resumable ingestion

Status: **implementation gate passed; cumulative acceptance remains blocked by inherited Phase 0 runtime gates**

## Checkpoint and lineage

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent reports: `docs/implementation/01-report.md`, `docs/implementation/02-report.md`
- Phase 02/03 code checkpoint: `78ed1e532fd7be9d9c28ce3e10ad5a13afdcf9e3`
- Config fingerprint: `a90848b9f9884c344d3fe2cc10cd6ec8c13da591`
- Baseline benchmark corpus fingerprint: `5820fa64bed3db3147d52d632975a21101893bff`
- Synthetic cyber fixture corpus SHA-256: `0991397298eaacd00c7225c7f2a4bc67189f8ee213481d5d9189c2fab13589ea`
- Synthetic record digests: `a540379933fd90225f599a8f867463475094c7be0e824ca09625d2e89967e9cf`, `1d48ac7b64cb3f0b6876993505549aa39ec6fdcd8ef754f1f823a719d993a483`
- No semantic model was used; ingestion fixtures are deterministic and offline.

## Implemented

Canonical metadata now models source manifests, raw snapshot references, source objects, immutable revisions/artifacts, retrieval observations, ingestion runs, checkpoints, quarantines, transactional outbox events, processed idempotency keys, dead letters, derivation dependencies, and revocations.

A bounded content-addressed filesystem object store stages raw and normalized bytes with SHA-256 checksums, explicit retention classes, atomic rename, maximum object size, immutable-path verification, and orphan enumeration.

`CanonicalMetadataStore` uses a DB-API transaction boundary. Deterministic tests use SQLite; production composition can reuse the repository's existing configured SQLAlchemy engine/pool through `manager.engine.raw_connection()`. The canonical module does not import SQLAlchemy or legacy configuration at import time.

The synthetic cyber connector/normalizer provides a two-record offline fixture with explicit source manifest metadata: JSON format, stable upstream identifiers, upstream versions, public fixture license/access, cursor updates, explicit revocation strategy, source-published availability basis, and exact/lexical/dense projection declarations.

For each accepted record:
1. raw bytes are staged immutably;
2. claimed digest is checked when supplied;
3. normalization is validated;
4. normalized bytes are staged immutably;
5. object/revision/artifact/observation identities are derived;
6. canonical metadata, dependencies, and the projection outbox event commit in one database transaction;
7. the page checkpoint advances only after the whole page is accepted or explicitly quarantined.

Poison records and checksum failures are quarantined independently so valid siblings survive. Failpoints prove behavior before metadata commit and after metadata commit. Revocation is idempotent, marks canonical revision state, records the revocation, and emits a deterministic projection-cleanup outbox event. Dependency traversal can enumerate downstream derived identities before projection cleanup is wired.

The outbox worker is at-least-once with deterministic idempotency keys, bounded attempts, and dead-letter state. A read-only `scripts/inspect_ingestion.py` reports counts/checkpoint/orphan counts without reading or printing credentials.

## Validation actually executed

Same cumulative command as Phase 02; **34/34 tests passed**, including **9 Phase 03 ingestion/outbox tests**.

Phase 03 acceptance fixtures passed:
- replaying the same batch preserves identical logical evidence counts/identities;
- interruption after raw staging leaves a discoverable orphan and does not advance the cursor;
- interruption after metadata commit resumes without duplicating artifacts/outbox events and does not falsely advance the page cursor;
- checksum-corrupt and poison records quarantine with explicit reasons while valid siblings commit;
- canonical metadata refuses references to missing objects;
- deletion/revocation dependencies are enumerable and cleanup events are idempotent;
- outbox replay uses the same idempotency key after a simulated crash;
- poison outbox work reaches dead-letter state after bounded retries;
- the production bridge reuses an existing manager engine connection rather than creating another credential/config path.

## Remaining blockers and handoff

The two historical Phase 0 gates remain blocked: the service-complete legacy fast/full runtime suite and B0 offline benchmark could not be executed in the connector environment. They remain required and are not treated as passes.

Independent next-phase implementation can proceed to the public cyber text vertical slice and real projections. Activation/promotion of the new runtime should remain blocked until the inherited Phase 0 gates execute successfully and the new MySQL/Milvus projection adapters are validated against a real service stack.

Rollback is additive-file reversal plus dropping unused canonical tables/objects only if they were explicitly activated later. This implementation did not mutate the live legacy database or object/index data.
