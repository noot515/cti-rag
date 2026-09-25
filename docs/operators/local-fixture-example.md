# Minimal local fixture example

This example exercises only redistributable/local fixtures and isolated temporary storage. It does not start external services, use credentials, or enable optional web/OpenCTI/RuntimePolicy integrations.

## 1. Run the local fixture profile smoke

```bash
export CTI_RAG_DATA_ROOT="$PWD/.cti-rag-local"
python scripts/phase22_profile_smoke.py \
  --profile deploy/profiles/fixture.json \
  --root "$CTI_RAG_DATA_ROOT/profile"
```

Expected properties: API-only exposure contract, local SQLite/filesystem stores, separate cache files, and bounded scheduler configuration.

## 2. Run the migration/query/rollback rehearsal

```bash
python scripts/phase24_migration_rehearsal.py \
  --root "$CTI_RAG_DATA_ROOT/migration" \
  --backup "$CTI_RAG_DATA_ROOT/backup" \
  --report "$CTI_RAG_DATA_ROOT/migration-report.json"
```

The rehearsal creates and queries a legacy lexical generation, creates a new generation, exercises the advanced-retrieval feature flag, observes the new query result, rolls back to the serviceable legacy manifest, re-publishes the new generation, tombstones a returned passage, and verifies that the tombstone hides the result. It then backs up and restores the isolated catalog/metadata/object state and verifies that the current manifest and revocation survive restore.

## 3. Run release conformance

```bash
python scripts/run_phase24_conformance.py \
  --report "$CTI_RAG_DATA_ROOT/conformance-report.json"
```

A blocked milestone is expected while required real-service/model/human-review gates remain unavailable. This is not an error in the fixture core; it is the release-readiness result.

## Rollback

The migration rehearsal uses the same atomic snapshot-pointer rollback contract used by the runtime. Production rollout is not authorized by this example, and the legacy compose file is not treated as a hardened production deployment.
