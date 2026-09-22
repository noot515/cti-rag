# Evidence runtime decision log

## D-0001 — Preserve legacy runtime during foundation work
Add a side-effect-free `cti_rag` package beside the historical `packages` package. The latter performs environment/config/model setup on import, which is incompatible with a minimal contract-only dependency boundary.

## D-0002 — Namespaced canonical JSON + SHA-256 identity
Use NFC Unicode normalization, sorted keys, explicit nulls, timezone-aware datetimes, finite numeric values, and structured namespace envelopes. Never concatenate identity fields with ambiguous delimiters.

## D-0003 — Observations are not revision identity
A repeated download of unchanged source content appends an observation to the immutable revision without changing `revision_uid`.

## D-0004 — Merge by citable identity, not text
Identical text from distinct revisions/editions remains separate. Retrieval-attempt IDs and ranking scores are non-citable metadata.

## D-0005 — First lexical target: MySQL 8 FULLTEXT
Prefer a dedicated derived FULLTEXT projection in the already deployed MySQL 8 service before adding another search service. Do not activate it until analyzer, filtering, snapshot, rebuild/rollback, and performance capabilities are validated.

## D-0006 — Effective scope is server-derived
Authenticated principal and tenant identity come from the trusted authentication boundary. Client payload fields can only narrow domains, sources, and labels; principal, tenant, and clearance-like fields are ignored rather than treated as grants.

## D-0007 — Policy precedes backend/model side effects
Authorization and mandatory capability checks run before search, traversal, structured execution, or model dispatch. Local-only evidence is never sent to a remote destination. Policy failure is fail-closed for protected access.

## D-0008 — Domain specifications stay pure
Cybersecurity, networking, quant, privacy, and humanities specs declare schemas, identifier parsers, query templates, relation rules, and fixtures without importing database/model SDKs. Runtime composition registers specs through `DomainRegistry`.

## D-0009 — Reuse the existing metadata engine, not legacy global imports
Canonical metadata uses a small DB-API transaction layer. Production composition can bind it to the existing manager's configured SQLAlchemy engine/pool via `raw_connection()`; minimal imports remain free of SQLAlchemy and legacy global configuration side effects.

## D-0010 — Stage objects before transactional metadata publication
Raw and normalized bytes are written immutably to bounded content-addressed storage first. Canonical metadata and the projection outbox commit atomically afterward. A database rollback never pretends to roll back object storage; unreferenced staged objects are explicitly discoverable as orphans.

## D-0011 — Outbox delivery is at-least-once
Projection events use deterministic idempotency keys, bounded retry counts, and dead-letter state. Consumers must make the idempotency key part of their side-effect boundary; replay after a crash is permitted and observable.
