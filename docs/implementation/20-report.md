# Phase 20 implementation report — optional read-only OpenCTI source integration

Status: **fixture/read-boundary gate passed; live OpenCTI lifecycle remains blocked; cumulative acceptance remains blocked**

## Lineage and validation

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/19-report.md`
- Validated code checkpoint: `10f59b356be07d85d88f605472a4a6e2e9399c9f`
- Actions run/job: `36112418435 / 107998666984`
- Python: 3.13.15
- Cumulative deterministic suite: **174/174 passed in 10.242 s**
- Phase 20 gate: **9/9 passed in 0.084 s**
- Affected legacy regressions: **8/8 passed**
- Registry audit through Phase 20 succeeded while intentionally remaining overall fail-closed.

## Upstream interface inspected and pinned

The optional adapter targets the official OpenCTI Python client interface inspected at OpenCTI commit `d100109622b67bb28d4e413d051a118d68ea89a4`, package version **pycti 7.260921.0**.

The integration uses documented read surfaces only:

- paginated `stix_core_object.list(..., withPagination=True)`;
- paginated `stix_core_relationship.list(..., withPagination=True)`;
- `get_stix_content(id)` for the canonical STIX export.

No OpenCTI mutation API is called.

## Implemented

### Optional source connector

`OpenCTIReadConnector` is isolated under `cti_rag.infrastructure` and imports `pycti` only inside `from_environment()`. Core/contracts/domains/planning and the normal API/worker/research requirements remain free of the optional SDK.

The connector provides:

- bounded opaque object/relationship cursors;
- page size capped at 100;
- bounded retry/backoff;
- deadline and cancellation checks;
- TLS verification enabled by default;
- optional CA bundle, client certificate, and explicit proxy configuration;
- exact raw wrapper bytes containing OpenCTI metadata plus exported STIX;
- full-sync reconciliation that can emit tombstones for missing prior STIX IDs;
- no deletion inference when resuming in the middle of a synchronization.

### Canonical normalization and restrictions

The domain-side normalizer is SDK-independent and maps the imported record into the existing immutable ingestion contracts. It preserves:

- OpenCTI ID and STIX standard ID;
- STIX object/relationship type and source/target refs;
- upstream created/modified/availability metadata;
- OpenCTI source metadata and object markings;
- external references;
- explicit `assertion_origin="imported_source"`;
- `locally_extracted_hypothesis=false`.

Supported TLP mappings are explicit. The most restrictive supplied marking wins. Non-public evidence is local-only. Unknown explicit mandatory markings are rejected so the existing ingestion pipeline can quarantine them; they are not guessed or downgraded. Absence of a marking is treated as an unmarked/public source record rather than a malformed marking.

### Existing lifecycle reused

Imported bytes enter the existing `SourceConnector -> IngestionPipeline -> immutable canonical store -> outbox -> projection/publication` path. Query-time code has no write-back path into OpenCTI.

Replay of identical source bytes is idempotent. An updated imported object creates a new immutable revision. Revoked/deprecated objects and completed-sync absences emit tombstones. A source outage does not change the already-published snapshot pointer.

Direct-source ATT&CK evidence and an OpenCTI-imported copy are related through identifiers but remain separate evidence/provenance records; matching text does not collapse source identity.

## Acceptance evidence

The Phase 20 fixtures validate:

- object pagination followed by relationship pagination;
- zero write calls;
- exact exported STIX retained with OpenCTI metadata;
- most-restrictive TLP mapping;
- unknown mandatory marking rejection;
- relationship marking preservation;
- imported assertions kept distinct from local hypotheses;
- replay idempotency;
- changed source -> new revision;
- revoked/missing source -> tombstone;
- mid-sync resume does not invent deletions;
- explicit source failure with current published snapshot unchanged;
- direct ATT&CK versus OpenCTI-imported record comparison without provenance collapse;
- minimal startup/import path remains free of `pycti`.

## Required blocked evidence

`phase20-live-opencti-read-lifecycle` remains **blocked**. No `OPENCTI_URL`, dedicated read-only token, or approved live OpenCTI instance was supplied, so live pagination, update, marking, deletion, and reconnect behavior is not reported as passed.

## Operator configuration

Operator guidance and an environment example were added under:

- `docs/operators/opencti.md`
- `config/integrations/opencti.env.example`
- `requirements-integrations.txt`

The optional dependency is not pulled into minimal startup.

## Migration and rollback

The source is additive and not enabled by default. Removing the optional connector/normalizer and integration requirements leaves existing immutable evidence/snapshots untouched. No migration rewrites canonical records.

## Handoff

Phases 19 and 20 are implemented with their deterministic/fixture gates passing. Cumulative acceptance remains blocked by Phase 14 plus inherited and live external-system gates.
