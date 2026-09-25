# Phase 22 implementation report — deployment profiles, safe caches, observability, and recovery

Status: **local deterministic operations/recovery gate passed; live staging/full-research infrastructure gates remain blocked; cumulative acceptance remains blocked**

## Lineage and executed validation

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/21-report.md`
- Validated code checkpoint: `7ce8fe6f3a6d5948725eea9750e035a68069770f`
- Actions run/job: `36117845446 / 108016031013`
- Python: **3.13.15**
- Cumulative deterministic suite through Phase 22: **192/192 passed in 58.587 s**
- Phase 22 invariant gate: **9/9 passed in 1.492 s**
- Affected legacy API regressions: **8/8 passed**
- Phase 8 backend-failure versus empty-evidence semantics were rerun as part of the cumulative suite.
- Cumulative registry through Phase 22 succeeded while intentionally remaining fail-closed.

## Deployment profiles

Four versioned profiles live under `deploy/profiles/`:

- `fixture`
- `text-mvp`
- `analytical`
- `full-research`

Each profile declares the existing service identities it uses, API-only external port contract, internal networking, per-service egress mode, configurable `CTI_RAG_DATA_ROOT`, resource limits, restricted read-only config mounts, capability drops, and bounded interactive/ingestion scheduler limits.

The Phase 22 path does **not** treat the legacy `docker-compose.yml` as a hardened production deployment. Existing service names are mapped for compatibility, but the legacy compose file's historical published backend ports/default credentials are not silently reclassified as secure.

Hardened profile secrets are names only. `resolve_profile_secrets` requires mounted `<SECRET_NAME>_FILE` inputs and rejects literal secret values in the hardened profile environment.

Fixture and text-MVP profile-contract smoke commands were executed only against isolated temporary storage; no user-running services or external host were modified.

## Safe caches

`SQLiteScopedCache` keys bind:

- principal/security namespace;
- effective-scope hash;
- policy epoch;
- normalized query and exact identifiers;
- snapshot ID;
- temporal mode/cutoff;
- plan/config/model fingerprints;
- locale;
- cache kind.

Private/public query caches and private/public embedding caches are physically separate SQLite stores. Empty and failed retrievals have distinct negative-cache states. A policy-epoch change yields a different key, and revocation invalidation removes targeted entries independently of TTL.

## Scheduling and cancellation

`BoundedScheduler` provides separate interactive and ingestion queues, capacity rejection, interactive preference with bounded burst fairness, and cancellation. Profile scheduler limits are executable inputs rather than documentation-only numbers.

## Observability

Default operational telemetry records query digests and an allowlisted set of stage metrics rather than raw queries/snippets/credentials. Protected debug traces require separate authorization. Freshness lag and projection ready/visible/integrity state are exposed. Concurrent generation/reranking RAM/VRAM capture records VRAM only when an actual sampler/runtime exists; otherwise the status is explicitly unavailable.

## Backup, restore, rebuild, tombstones, and rollback

Canonical metadata now has portable JSON backup/restore in addition to the existing snapshot-catalog backup.

`RecoveryManager`:

- checksum-backs up immutable object bytes;
- backs up canonical metadata and snapshot catalog/pointer/revocations;
- verifies checksums before restore;
- restores object identity before metadata;
- verifies the published manifest pointer after restore;
- rebuilds a fixture derived-index representation from the restored published manifest;
- preserves revision IDs, payload IDs, citation locator JSON, and text digests;
- propagates pending cache invalidations and projection cleanup tasks;
- rolls back only to an already-serviceable immutable manifest;
- exposes operator health state.

Tests verify restart persistence for ingestion checkpoints and published snapshot pointers, restore identity/citation preservation, tombstone/cache invalidation independent of TTL, and rollback rehearsal.

## Tested operator commands

The following command surfaces are executed by the Phase 22 test gate against isolated temporary roots:

`scripts/phase22_profile_smoke.py`

`scripts/phase22_recovery.py health`

`scripts/phase22_recovery.py backup`

`scripts/phase22_recovery.py restore`

Direct manager tests additionally execute fixture derived-index rebuild and catalog rollback with a nonempty published snapshot.

## Fingerprints

Repository blob fingerprints at the validated checkpoint include:

- cache: `b63fa3be803a62bc69854660368bfe65a86144ff`
- scheduler: `425601f7ba394886e6f7d15fb5d1161dd9aae8e6`
- telemetry: `3425887847fa4f4375c69c76993d4bb4b6fd5cba`
- profile loader: `212181902901c39da427e6c9bbfb144a08b884dd`
- recovery: `637e80d4a3f5dfdae511b030c75d777821567cd7`
- secret resolver: `fee9b88aef2dcf28e820ec69fe61b81fa8f4fb5f`
- canonical metadata backup/restore: `96c63c328f83aed384bc54f573cae944d3d51313`
- Phase 22 tests: `263f6647c13138f22a9d1fd4e0acfd4152e73eb9`

## Blocked required evidence

These Phase 22 gates remain blocked:

- `phase22-text-mvp-live-profile` — no full MySQL/Redis/RabbitMQ/dense staging stack was started.
- `phase22-analytical-live-profile` — no real analytical/Neo4j/Milvus recovery lifecycle was run.
- `phase22-full-research-live-profile` — depends on still-blocked approved web/OpenCTI/RuntimePolicy/model services.
- `phase22-live-concurrent-model-memory` — no approved live concurrent model/GPU runtime was present.

Production service-specific backup/index rebuild and egress enforcement therefore remain live-infrastructure evidence, not fixture passes.

## Migration and rollback

The new operational layer is additive. Existing evidence and snapshot schemas remain intact. Canonical backup/restore serializes existing tables rather than rewriting IDs. Profiles are not automatically activated. Rollback is an atomic pointer move to a serviceable prior manifest and continues to honor current revocations.

## Handoff

The independent core work requested by Phase 22 is implemented and deterministic gates pass. A subsequent phase may proceed, but cumulative release promotion remains blocked until Phase 14 and the required real-service/model/human-review gates are satisfied.
