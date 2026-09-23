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


## D-0031 — Graph identity is namespaced and typed; display names never define identity
Graph entities use a deterministic `entity_uid` derived from namespace, entity type, and canonical identifier. Name similarity is only a provisional resolution signal. Sourced identity decisions distinguish `confirmed_same_entity`, `possible_same_entity`, and `alias_of`; only confirmed links of compatible entity types participate in confirmed equivalence closure.

## D-0032 — Graph authorization and temporal eligibility are applied before adjacency exists
The reference GraphPort filters canonical entities by tenant/access/processing policy and current revocation, then filters each source assertion by requested source scope, assertion policy, revision/support availability, snapshot membership, current revocations, and temporal validity before constructing traversal adjacency. Source/time eligibility belongs to the assertion that makes the claim rather than whichever source-specific projection first introduced a shared canonical entity. Hidden private bridge nodes and edges therefore cannot consume public degree/edge budgets or change public path-count/truncation behavior.

## D-0033 — Graph traversal is typed and bounded rather than arbitrary Cypher
Query plans can invoke registered traversal templates containing allowed predicates, endpoint types, and directions. The runtime defaults to at most two hops, eight seeds, degree 20, 100 paths, a bounded examined-edge count, one request deadline, and cancellation propagation. The Neo4j adapter exposes fixed schema/upsert operations rather than a model/client arbitrary-Cypher surface.

## D-0034 — Ontology mappings are not behavioral observations
CVE→CWE, CWE→CAPEC, CAPEC→ATT&CK, and similar chains are labeled as ontology/source mappings when their source assertions exist. They are not automatically described as exploitation, causation, ownership, attacker intent, or observed technique use. Longer chains are composed from bounded traversals rather than silently raising the graph hop limit.

## D-0035 — Graph paths remain typed evidence outside passage RRF
GraphPathHit carries the node chain, assertion UIDs, source-backed provenances, relation types, epistemic labels, source/policy metadata, mapping semantics, and truncation status. Query-DAG fusion and context packing retain these typed paths separately from passage reciprocal-rank fusion. Final response admission rechecks current scope and revocations before serialization.

## D-0036 — Cyber source adapter status distinguishes fixture validation from live validation
ATT&CK STIX 2.1, CVE JSON 5.x, and CISA KEV adapters are `fixture_validated` using small fictitious records encoded in their real upstream shapes. They are not `live_validated` until network fetch/update/delete/rebuild reconciliation executes against the pinned upstream source. Deferred source families remain explicitly deferred rather than sharing a misleading generic parser.

## D-0037 — Source revisions are preserved; updates and removals are tombstones, not mutation
Changed upstream content creates a new immutable revision while prior raw/normalized bytes remain addressable. ATT&CK revoked/deprecated objects, explicit source deletions, and detected KEV catalog removals enter the current revocation overlay and projection-cleanup lifecycle. Empty post-deletion lexical generations retain a pinned analyzer identity so coherent empty snapshots remain publishable.

## D-0038 — CVSS assessments remain source/version-specific evidence
CVE normalization retains CVSS scheme/version, score, severity, vector, and source container independently. Multiple CNA/ADP assessments are not averaged or overwritten into one severity truth. KEV membership is a separate structured eligibility fact.

## D-0039 — Cyber graph edges require explicit source mapping fields
The cyber projector emits CVE→CWE only from explicit CVE `problemTypes.cweId` evidence and attaches its source locator/qualifier. A declared CWE mapping missing a valid `cweId` is quarantined. No CAPEC/ATT&CK edge is inferred merely from text similarity or identifier co-occurrence.

## D-0040 — Source manifests carry provenance/licensing/parser identity
Core cyber source manifests record upstream source URI, source terms/license identifier and notice, connector fingerprint, parser/normalizer fingerprint, availability basis, update semantics, deletion semantics, retention class, and supported projections. Runtime source content remains inert evidence; source records cannot grant tool permissions or executable authority.


## D-0041 — Networking semantics are represented as distinct evidence relations
BGP `announced_by`, RPKI `authorized_origin`, and RDAP `registered_to` remain distinct source assertions with their own source, observation/valid interval, and qualifiers. DNS answers remain time- and vantage-specific structured observations and never become ownership assertions. Graph relation requests are enforced during expansion so a request for one relation cannot silently traverse another.

## D-0042 — IPv6-capable containment uses ordered 128-bit range values without backend IP extensions
The typed `IP_IN_PREFIX` operator remains schema-controlled. Existing numeric IPv4 fixtures retain integer range fields; IPv4/IPv6-capable networking schemas store zero-padded 128-bit hexadecimal range bounds plus an explicit IP-family field. Lexicographic range comparison is therefore deterministic for both families without enabling arbitrary DuckDB filesystem/network extensions.

## D-0043 — RFC citations are section-addressable and obsolescence is evidence, not deletion
RFC canonical identity uses the RFC number, while explanatory passages use `CanonicalPassageLocator("rfc-section", "RFC N#section")`. Updates/obsoletes relationships remain source assertions. An obsolete RFC stays retrievable as its own preserved document and exact evidence explicitly reports its obsolescence metadata.

## D-0044 — Tickers are exchange- and interval-qualified aliases, not issuer identity
Issuer CIK, security ID, exchange, and ticker alias intervals are modeled separately. A ticker resolver requires both exchange and a timezone-aware point in time and rejects ambiguous or missing matches. Historical universe membership and delisted securities remain queryable according to their recorded intervals.

## D-0045 — Financial calculations consume point-in-time StructuredResult inputs
Returns and event-study calculations do not scan raw fixture rows directly. They obtain price observations through the existing Prompt 09 structured/temporal engine, so availability cutoff, logical-key revision precedence, scope, snapshot, and revocation semantics are applied before calculation. Derived outputs preserve input revision/provenance manifests and calculation versions.

## D-0046 — Event-study outputs are associations, not causal or profitability claims
The event-study specification pins target security, benchmark security, estimation/event windows, simple close-to-close return definition, missing-data rejection rule, provider, currency, and calculation version. The verified output reports abnormal-return association only; retrieved co-occurrence or computed abnormal return does not establish causation, predictability, or trading profitability.

## D-0047 — Finance/network source readiness distinguishes fixture mechanics from live entitlement
RFC, BGP/RPKI, DNS/RDAP, SEC, FRED/ALFRED, price, corporate-action, and security-master fixture adapters may be `fixture_validated` while their live source lifecycle remains blocked or deferred. Synthetic licensed-file fixtures do not imply a production market-data license, provider entitlement, or access to an unprovided feed.


## D-0048 — Humanities search normalization never replaces the citable transcription
Humanities passages preserve source/original transcription separately from a normalized search representation. OCR cleanup, Unicode normalization, and analyzer-specific forms may improve retrieval, but a quotation resolves through the original passage plus TEI/IIIF/canonical provenance. Search normalization is derived evidence, not an editorial rewrite of the source.

## D-0049 — Historical uncertainty is represented as intervals and precision labels, not fabricated instants
Humanities date metadata uses bounded intervals and explicit precision such as exact date, month, year, range, approximate, or uncertain. Month/year/uncertain source dates remain structured interval evidence and do not become exact `valid_from` instants. Interval-overlap queries operate on the declared bounds.

## D-0050 — Work, edition, witness, translation, passage, page, article, and institution are separate identities
Humanities identity is namespace/type-qualified. An edition is related to a work; a witness is related to an edition; a translation is another edition with an explicit `translation_of` assertion. Editorial notes and scholarship are separate passage roles. They do not become primary-source quotations merely by sharing a document container.

## D-0051 — Humanities rights/readiness is source- and item-specific
The validated Gutenberg text fixture is explicitly scoped as public-domain-in-the-USA material; TEI and newspaper/IIIF fixtures are synthetic source-shaped records. A source-level rights statement does not erase item-level review requirements. BigLAM, DPLA, Europeana, museums, and other archives remain deferred until source-specific rights, update, provenance, and analyzer contracts are pinned.

## D-0052 — Cross-domain joins use typed keys plus source-backed support, never display names
A join key is a `(namespace, entity_type, canonical identifier)` triple. Typed join records additionally carry relation type, source, provenance, policy, availability, and validity interval. When bound to a snapshot catalog/evidence store, every supporting revision must belong to the pinned manifest, remain unrevoked, and resolve to evidence. Display-name equality is never sufficient to satisfy a join.

## D-0053 — Unresolved joins block dependent graph and calculation nodes
A required join may resolve, remain ambiguous, be missing, be time-incompatible, expose suggestion-only candidates, or be rejected. Only `resolved` may feed a dependent graph traversal or verified calculation. Ambiguity is returned as partial evidence; the runtime does not choose an arbitrary candidate to keep the DAG moving.

## D-0054 — Graph suggestions are not confirmed cross-domain identity
Graph-derived candidate keys may be returned separately as suggestions, but they cannot satisfy a confirmed typed-join obligation. This preserves a distinction between exploratory association and source-backed identity/relation evidence.

## D-0055 — Cross-domain completeness is obligation-based and replayable
Each evidence obligation receives a status and citation count. Required unsatisfied obligations become explicit gaps in the advanced evidence response. Replay traces record plan/configuration identity, snapshot, node statuses, typed-join decisions, and structured-calculation input lineage. Passage fusion remains passage-only; exact, graph, structured, and join evidence stay typed outside reciprocal-rank fusion.

## D-0056 — Global budgets and subquestion coverage survive cross-domain expansion
Cross-domain plans are rejected before execution when backend-call/candidate/context budgets are exceeded. Passage fusion and context packing preserve coverage across subquestions so a large corpus cannot consume all packed context before a required smaller-domain subquestion contributes evidence.

## D-0057 — Phase 14 remains an explicit prerequisite blocker
The current branch contains no Phase 14 implementation/report. Phases 15 and 16 can therefore pass their own independently executable gates, but cumulative acceptance through Phase 16 remains fail-closed until Phase 14 and its required evidence are supplied. The missing phase is not silently inferred or marked complete.
