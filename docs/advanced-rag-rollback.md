# Advanced RAG retained-generation rollback

Updated: 2026-09-19

## Safety invariant

Rollback switches only the active generation pointer to a retained, verified generation
inside the current evidence catalog. Do not restore an old catalog/database backup as
the normal rollback mechanism: doing so could erase newer revocation, deletion,
visibility, merge, or lease state.

The live lifecycle/tombstone overlay remains authoritative after a generation restore.
A prior generation is therefore recoverable for content/index regression without
re-authorizing evidence that has since been withdrawn.

## What must be pinned for every promoted generation

Record the following in the release record before promotion:

- domain, scope_id, and corpus_id;
- generation_id and manifest_sha256;
- repository/deployment commit;
- every required projection fingerprint and verified receipt;
- the immediately prior retained generation_id and manifest_sha256;
- policy/freshness release evidence used for the promotion.

Do not pin credentials, tokens, signing material, or restricted raw payloads in the
release record.

## Restore prerequisites

The target generation must still exist in generation_manifests, be ready or active, and
have all enabled projection receipts verified. Current catalog and lifecycle state must
be healthy enough to evaluate tombstones and freshness. If those conditions are not
true, hold the release and repair the catalog instead of forcing a pointer.

## Operator restore

Use the same current state directory that contains the active evidence catalog. Replace
only the placeholders below.

POSIX or PowerShell can run the same Python file:

~~~
from pathlib import Path

from benchmark.advanced.release_readiness import restore_retained_generation
from packages.evidence.store import EvidenceStore

state = Path("<advanced-state-dir>")
with EvidenceStore(state / "catalog.db", state / "raw") as store:
    result = restore_retained_generation(
        store,
        domain="<domain>",
        scope_id="<scope-id>",
        corpus_id="<corpus-id>",
        target_generation_id="<retained-generation-id>",
    )
    print(result)
~~~

The helper rejects a missing, failed, unverified, or non-ready retained generation. It
does not touch OpenCTI, seed upstream data, mutate credentials, or disable policy.

## Post-restore verification

Before resuming service:

1. Verify active_generations points to the exact pinned generation_id and
   manifest_sha256.
2. Verify every required projection receipt for that generation is still valid.
3. Re-run freshness and authorization checks against the current lifecycle state.
4. Verify a revision tombstoned after the retained generation was created remains
   withdrawn. The focused Prompt 22 test exercises this boundary.
5. Run a restricted-evidence negative test and a permitted-evidence smoke query.
6. Record the restore event, previous generation, restored generation, reason, and
   command outcome without secret values.
7. Keep advanced retrieval opt-in until the release owner explicitly authorizes
   resumption.

A rollback is not a policy rollback. Current revocations, visibility losses, and lease
expiry continue to block serving even when the restored generation contains those
historical revisions.

## Roll forward

After the fault is corrected, build and verify a fresh generation through the normal
publication path. Do not delete the retained generation or raw provenance merely to
force convergence. Promote the new generation only after the same release gates are
re-evaluated.

## Current verification status

The rollback mechanism and its current-revocation-overlay test are implemented in
Prompt 22. The exact Python 3.11 focused test and a production restore drill remain
not_run until executed in the target validation environment. A code implementation is
not recorded as a successful production rollback drill.
