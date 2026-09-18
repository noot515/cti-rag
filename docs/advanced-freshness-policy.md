# Advanced freshness and visibility policy

Prompt 21 treats an immutable content generation as evidence history, not as a
permanent authorization grant.

## Inventory and withdrawal

Only a successful, complete and authorized inventory may compare missing
previously visible source IDs. A timeout, access failure, incomplete pagination
or changed checkpoint/filter namespace records a failed inventory and does not
mass-delete prior evidence.

Missing source IDs from a complete inventory are classified
`no_longer_visible` unless the source explicitly states `revoked` or
`upstream_deleted`. The stronger reasons are never inferred from absence.

A new revision for an existing source object retires the superseded revision
without deleting retained provenance. Explicit merge mappings are stored with
their source provenance; they do not automatically collapse identities across
sources.

## Visibility leases

Every successful reconciled inventory renews a scoped lease. Maintained live
serving requires an explicit `max_staleness_seconds`; expiry fails closed.
The public/sanitized fixture uses the documented mechanics value of 86400
seconds. The suggested poll overlap is 300 seconds and full inventory interval
is 86400 seconds. These are configuration values, not immediate withdrawal
guarantees.

POSIX example:

    export ADVANCED_RAG_OPENCTI_MODE=live
    export ADVANCED_RAG_ALLOW_OUTBOUND=true
    export ADVANCED_RAG_OPENCTI_API_URL=https://opencti.example
    export ADVANCED_RAG_OPENCTI_MAX_STALENESS_SECONDS=3600
    export OPENCTI_API_TOKEN=<read-only-token>

PowerShell example:

    $env:ADVANCED_RAG_OPENCTI_MODE = "live"
    $env:ADVANCED_RAG_ALLOW_OUTBOUND = "true"
    $env:ADVANCED_RAG_OPENCTI_API_URL = "https://opencti.example"
    $env:ADVANCED_RAG_OPENCTI_MAX_STALENESS_SECONDS = "3600"
    $env:OPENCTI_API_TOKEN = "<read-only-token>"

Credentials are never stored in inventory, lease, checkpoint or report rows.

## Request-time enforcement

Grant-aware policy revalidates the corpus grant and freshness lease. Retrieval
also rechecks this authority before reranker egress, before context packing and
again immediately before returning a result. Revision tombstones are consulted
as a live overlay even for older pinned generations.

Thus retained generations remain useful for provenance/recovery but become
nonservable when authorization or visibility expires.
