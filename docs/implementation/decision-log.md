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

## D-0012 — The catalog pointer is the cross-backend publication authority
Projection writes are staged and immutable. A generation is not serving state until readiness includes serving visibility and referential integrity, all required projection generations agree on the evidence revision set, and one metadata catalog pointer is atomically advanced to the immutable manifest.

## D-0013 — Current revocation overrides immutable snapshots
Pinned snapshots remain immutable for reproducibility, but a separate current revocation overlay is checked by backend retrieval, canonical hydration, and response admission. Cache invalidation and projection cleanup can complete asynchronously after the deny overlay has made revoked evidence inaccessible.

## D-0014 — Exact identity is not textual mention
Canonical exact lookup is namespace- and object-type-aware and never uses fuzzy matching. Reports or passages that merely mention an identifier remain lexical evidence and do not become canonical exact records. Revision selection additionally respects scope, availability, validity interval, and current revocation.

## D-0015 — MySQL FULLTEXT remains the production candidate; SQLite FTS5 is the validated local integration backend
The MySQL 8 FULLTEXT adapter reuses the existing configured connection pool and implements the same generation/scope/snapshot contract, but the real MySQL service has not been executed in this environment. SQLite FTS5 provides a persistent actual-backend integration fixture for restart, filtering, publication, and tombstone behavior; it is not evidence that MySQL production readiness has passed.

## D-0016 — Embedding compatibility is a first-class immutable identity
Dense representations are compatible only when provider, model revision, tokenizer revision, vector dimension, pooling, normalization, distance metric, and deterministic context-prefix revision all match. The complete fingerprint participates in cache, representation, collection, and snapshot generation identity.

## D-0017 — Embedding authorization happens before provider-visible text is assembled
Uncached source or query text is authorized against the effective scope, processing labels, operation, and destination before the runtime builds a model request. Embedding caches are separated by security namespace and complete embedding fingerprint, and the queue/batch/concurrency/retry bounds are server-controlled.

## D-0018 — Preserve legacy Milvus behavior; create compatible deterministic-ID collections beside it
The historical `KnowledgeBase` path keeps its random INT64 keys and remains untouched. The new dense SearchPort uses full deterministic passage UIDs as VARCHAR primary keys and fingerprint-separated collection names. This avoids a risky in-place migration while making dense evidence joinable to canonical passages.

## D-0019 — ANN output is a candidate set, not canonical evidence
Dense backend rows must hydrate through the canonical EvidenceStore before they can become citable hits. A missing, mismatched-revision, or mismatched-locator passage fails closed rather than trusting stale index text. Current revocation is also applied before hydration.

## D-0020 — Deterministic planning precedes optional semantic planning
Identifier/date/unit parsing, task templates, authorized domain routing, evidence obligations, and budget validation execute before any optional model planner. Plans carry immutable effective scope and snapshot references; model output cannot grant domains, calls, candidates, or budget beyond server bounds.

## D-0021 — Fusion is passage-only and resistant to rewrite vote multiplication
Exact and structured obligations remain outside passage-ranking competition. Passage fusion uses equal-weight RRF with stable passage-ID tie-breaking; repeated identical query variants do not create extra votes, variants are normalized within a channel, channels are fused afterward, and final selection round-robins across subquestions to preserve coverage.

## D-0022 — Deterministic fake embeddings prove mechanics, not semantic retrieval quality
Offline deterministic embeddings are used only to validate cache isolation, identity, authorization, snapshot filtering, fusion, and lifecycle mechanics. Actual embedding-model quality and actual Milvus ANN behavior remain explicit blocked gates until executed on the pinned runtime.


## D-0023 — Reranking is optional and occurs only after canonical authorization/hydration
The single text reranker receives only canonically hydrated passages whose tenant, access label, processing class, snapshot, revision, and locator were validated. A reranker failure never becomes an authorization bypass: fused ranking is retained with explicit degradation metadata. Exact and structured obligations do not enter text reranking competition.

## D-0024 — Context budgets use the target tokenizer interface, not character estimates
Context packing consumes a TokenizerPort compatible with the configured generator tokenizer, reserves instruction/tool/output tokens, and applies the plan's server-bounded context limit. Truncation occurs on tokenizer boundaries and citations are re-resolved against canonical evidence afterward. Actual configured generator-tokenizer execution remains a separate external gate when the model runtime is unavailable.

## D-0025 — Advanced retrieval is evidence-only, explicitly injected, and disabled by default
`POST /research/advanced-retrieval` returns typed evidence rather than generating an answer. The FastAPI router does not construct models, stores, or policies on import. `CTI_RAG_ADVANCED_RETRIEVAL_ENABLED` plus an explicit runtime binding is required; legacy endpoints remain unchanged/default. Debug traces require a policy grant distinct from normal evidence access.

## D-0026 — Retrieval traces are privacy-minimized
Default traces contain a normalized-query digest, scope hash, plan/configuration hash, snapshot, policy epoch, model/tokenizer fingerprints, channel statuses, and timing. Raw queries and private snippets are not trace fields. Public diagnostics expose typed status/reason codes rather than denied titles, counts, backend SQL, or credentials.

## D-0027 — Structured analytics accept typed specifications, never raw model SQL
The analytical surface is a server-owned DatasetRegistry plus typed predicates, joins, grouping, aggregations, ordering, and approved functions. Dataset/table/field identifiers are resolved from registered schemas; client values are parameterized. Raw SQL, arbitrary paths, and unrestricted functions are rejected rather than sanitized heuristically.

## D-0028 — The validated DuckDB profile uses preloaded tables with external access disabled
Prompt 09 is validated against an actual DuckDB runtime using server-preloaded deterministic tables. External filesystem access and unsigned extensions are disabled, memory/threads/scan rows/wall time are bounded, and output row limits are distinct from scan/aggregation semantics. Approved Parquet paths can be added later without widening the client query language.

## D-0029 — Public-knowledge time and system-replay time are different contracts
Historical-public mode requires trustworthy non-null availability at or before the cutoff and applies dependency availability. Historical-system-replay selects rows actually present in the requested system manifest, including dependency-manifest compatibility. Source revision precedence is applied per logical key after temporal/scope eligibility. Unknown availability is either conservatively excluded or causes explicit rejection according to the typed query policy.

## D-0030 — Verified structured outputs remain typed evidence outside passage RRF
StructuredResult records dataset snapshot, query-spec hash, typed values/units, null rules, temporal mode, calculation fingerprint/version, and reproducible input lineage. Context packing reserves space for verified structured obligations directly; arbitrary table row order is never converted into passage-ranking votes.
