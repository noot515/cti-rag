# Current state and sequencing handoff

Prompt 22 is stacked on the Prompt 21 frozen handoff
`5a9d1e6807bf9261c3d42e088234061e3b046c91` on
`feat/advanced-22-release-readiness`. Prompt 22 implementation/test head before final
handoff documentation is `25a68f1f5c2308289065eafaded36d14740c7c97`.


Reconciliation notes:

1. Prompt 16 remains the authenticated native HTTP boundary. Prompt 17 evaluates native advanced retrieval mechanics beside the legacy benchmark and does not change route defaults or legacy algorithms.
2. Retrieval execution is label-blind: fixture query records are checked for answer/qrel fields, the grouped split is frozen, and exact/lexical/dense/graph predictions are frozen before object qrels or path annotations are opened.
3. Exact/lexical/dense/graph fixture results still pass the public-fixture authorization policy. There is no authorization ablation in the evaluation matrix.
4. Target-object ranking is deduplicated before Hit/Recall/MRR/nDCG. Complete-path scoring requires an entire acceptable ordered-object alternative; a prefix/broken path is not partial credit.
5. Evidence-document metrics require their own labels. Existing fixture object qrels are not silently reused as document labels.
6. Citation validity and independently judged claim support are different metrics. Citation validity never creates a support score when a judge annotation is missing.
7. Unanswerable false-evidence and abstention rates are separate contracts. The current offline answer runner reports them `not_run` because no answer generator is configured.
8. The grouped split uses both object/report cluster and near-duplicate query family, including transitive unions, before producing deterministic seed/grouping/split hashes. No held-out labels are used to form groups.
9. R1-R6 and C1 are preregistered with fixed top-k, pre-rerank and context budgets. R1=dense, R2=lexical, R3=dense+lexical, R4=+exact, R5=+graph, R6=+single final reranker; C1 compares basic/structured formatting under equal budgets.
10. The fixture config has deterministic local embedding but no final reranker/generator/judge. R6, C1 answer/context quality and answer/judge metrics therefore remain null `not_run`; no fallback ranking is mislabeled as reranker quality.
11. L0 object retrieval remains `not_comparable` without a canonical legacy object mapping. The legacy comparator itself is not modified to improve scores.
12. The one-command retrieval report writes validated/secret-free config, environment, corpus and frozen split snapshots, per-query records, retrieval/answer/latency metrics, ablation CSV and Markdown. Failed queries/timeouts remain in per-query output; latency states sample count/concurrency/cache state and no throughput claim.
13. Paired cluster bootstrap is fixed at 2,000 resamples by default. A lower 95% bound >= -0.01 is the noninferiority criterion. Graph gain is computed only on the mapping subset and requires lower bound > 0. Missing/small independent clusters are `inconclusive`.
14. Catalog mapping on the synthetic fixture is not a held-out-edge generalization experiment. Held-out-edge and real-quality promotion gates remain separately `not_run` until adequate grouped held-out data exists.
15. Optional future generator/judge egress requires explicit permission plus exact model identifiers. This phase ships no default model/judge adapter, so the required offline answer command remains network-free and reports unavailable metrics honestly.
16. `scripts/validate_advanced_04_17.py` is the strict target handoff: predecessor P04-15 chain -> P16 API/import safety -> P17 metrics/report tests -> both fixture report commands -> compile/diff/full collection/status/HEAD.
17. Prompt 16's advanced fixture app remains an injected-runtime application boundary; Prompt 17 directly exercises the concrete local exact/lexical/dense/catalog-graph fixture indexes. The Prompt 16 ASGI exit gate must still demonstrate the final injected runtime wiring before deployment promotion.
18. The implementation sandbox still has Python 3.13.5, no Python 3.11, no Docker and no direct GitHub/package DNS. Exact target tests/report commands remain `not_run` here rather than inferred from implementation.


Prompt 18 reconciliation notes:

1. The external CTIConnect source is pinned to commit `554797d69a51147f1f98fad7198cb2d2b183d0e9`, whose audited manifest contains 1,859 QA pairs and VCA=219. The later upstream 1,860/VCA=220 state is not accepted by this phase without a new audit.
2. CTIConnect stays outside application runtime dependencies and is located by `CTICONNECT_PATH`. No data files are vendored.
3. Query-only records exclude answers, ground truth, target IDs, source clusters and construction provenance. Source provenance may be used only for frozen split grouping/scoring metadata, never as retrieval query content.
4. Structured record identity is based on source identifiers, not the globally repeated outer numeric IDs. Nested `contents` JSON is validated before indexing.
5. Reports use only supplied executive-summary data and validated `BLOG-<id>` mapping; there is no automatic full-text download.
6. Official answer metrics and custom retrieval metrics remain distinct. Source-document qrels are nonexhaustive proxies, not evidence/path labels.
7. Extracted `cskg` assets are lineage metadata only in this phase. The serialized BM25 pickle is never loaded; BM25 is rebuilt from text.
8. Missing CTIConnect checkout or real model configuration is an explicit `not_run` operational/quality gate and does not block purely offline code continuation, but it cannot authorize benchmark promotion.
9. `scripts/validate_advanced_04_18.py` chains the complete Prompt 04-17 validator before any Prompt 18 gates and finishes with compile/diff/full-collection/status/HEAD checks.


Prompt 19 reconciliation notes:

1. The live client/server compatibility target is intentionally narrow: OpenCTI `7.260914.0` and pycti `7.260914.0`. Newer pycti releases are not silently accepted without rerunning this phase's reader and live integration gates.
2. Only `packages/integrations/opencti/client.py` constructs `OpenCTIApiClient`. Reader, normalizer, sync and CLI layers depend on the restricted page-transport surface and cannot call mutation APIs.
3. Capture uses bounded `first` plus opaque `after/endCursor` pagination, ordered by OpenCTI `updated_at`. The STIX `modified` value remains semantic provenance and revision input; it is not replaced by platform maintenance metadata.
4. A finite completed scan records start/end interval and consistency warnings. It does not claim upstream point-in-time snapshot semantics because OpenCTI can change during traversal.
5. Repeated/nonadvancing cursors, exhausted limits, transient failure after retries, access denial, malformed pages or a final count deficit block complete publication.
6. Sanitized recorded captures are the default test/CLI path and make no network calls. Live mode requires explicit network enablement and a token read only from the configured environment-variable name.
7. Captured Attack Pattern, Vulnerability, Report and explicit STIX relationship shapes normalize through the existing CTI evidence contracts. CWE/CAPEC are emitted only from demonstrated identifiers/fields; unsupported relationships or malformed records are quarantined with counts.
8. Unmarked live evidence remains unresolved/restricted rather than being promoted to public by a request flag. Sanitized fixture mode alone injects a TLP:CLEAR fixture marking.
9. Publication reuses the durable catalog and atomic generation path with exact, lexical and catalog-graph projections. There is no query-time upstream fallback and no streaming/incremental completeness claim.
10. `scripts/validate_advanced_04_19.py` chains `validate_advanced_04_18.py` before Prompt 19 gates, so unresolved Python 3.11 predecessor correctness remains visible rather than being replaced by later tests.
11. The current sandbox has Python 3.13.5 and cannot resolve GitHub/package hosts from the container; Python 3.11, pinned pycti installation and live OpenCTI are therefore recorded as `not_run` rather than inferred successes.


Prompt 20 reconciliation notes:

1. The existing generic `checkpoints` table is retained for backward
   compatibility; OpenCTI replay uses a new namespaced ledger because Prompt 20
   requires type/filter identity plus independent ingestion/published cursors.
2. The initial implementation intentionally performs a full fresh generation
   rebuild after a completed capture. The page ledger is durability/replay
   state, not a claim that opaque OpenCTI cursors prove global completeness.
3. Raw page bytes are written content-addressed before the ledger transaction.
   Orphan raw blobs after a crash are safe; the ingestion cursor advances only
   with the page receipt/job transaction.
4. Prompt 06 projection jobs remain the authoritative per-backend
   acknowledgement ledger. Prompt 20 links an ingestion run to the generation
   and reconciles the activation-before-checkpoint crash window.
5. Capture timestamps were removed from semantic source snapshot identity.
   They remain recorded as capture/replay metadata; unchanged complete scans
   therefore replay with stable revision/source identity and zero catalog
   logical changes.
6. Duplicate source ordering is STIX `modified` first and OpenCTI
   `updated_at` only as a tiebreak. Equal versions with different content are
   ambiguous and fail closed.
7. `scripts/validate_advanced_04_20.py` chains every unresolved predecessor
   correctness gate before Prompt 20 tests.


Prompt 21 reconciliation notes:

1. Immutable generations remain content history; live authorization is a
   separate lease/tombstone overlay.
2. Complete authorized inventories are the only source of absence-based
   suppression. Timeouts, partial pagination, filter namespace changes and
   access failures cannot mass-delete evidence.
3. Missing records default to `no_longer_visible`; `revoked` and
   `upstream_deleted` require explicit upstream state.
4. Superseded revisions are revision-level tombstones. Reappearance can clear
   weak visibility-loss tombstones but never explicit revocation/deletion.
5. Explicit merge mappings retain provenance and retire the source view without
   automatic cross-source identity collapse.
6. Freshness is rechecked through grant-aware policy and immediately before
   reranker, packing and final result emission. Lease expiry denies serving from
   retained snapshots.
7. `scripts/validate_advanced_04_21.py` chains the complete Prompt 04-20
   correctness handoff before Prompt 21 tests and reconcile CLI execution.


8. Absence comparison is scoped to the exact source/type/filter namespace.
   A changed filter has no inherited absence baseline and therefore cannot
   mass-tombstone records from the prior filter.
9. The first visibility inventory may bootstrap absence only from an already
   published Prompt 20 checkpoint for the exact same namespace. Subsequent
   inventories compare against the prior successful inventory's seen IDs.
10. A record that is still seen upstream but cannot produce a current
    normalized/authorized revision suppresses its prior revision as `unknown`
    rather than continuing to serve stale evidence.
11. Scope freshness requires a valid lease for every source/type that has
    participated in the inventory history; a failed inventory for a previously
    required type cannot be masked by a fresh sibling type.


Prompt 22 reconciliation notes:

1. The implementation-plan language that calls OpenCTI the canonical CTI data plane is
   not treated as evidence that OpenCTI improves retrieval. Prompt 22 measures the
   source-equal C1-direct versus I1-OpenCTI path first; enriched OpenCTI remains a
   separate coverage experiment.
2. Stable local UIDs, local scope IDs and source_instance may differ across the direct
   and ingested paths. Matched identity therefore uses kind + upstream source_object_id
   + raw payload SHA-256. Names are never equivalence keys; transport differences are
   emitted separately.
3. Marking/policy content is semantic and may not be normalized away. Unexpected
   marking or other semantic normalization drift fails canonical parity and disables
   platform attribution.
4. The matched recorded fixture exercises deterministic exact/lexical mechanics only.
   ANN, real embedding/reranking/generation, live OpenCTI, real Milvus/Neo4j and judged
   quality remain separate not_run gates.
5. Prompt 17 thresholds remain unchanged: 2,000 paired cluster-bootstrap resamples,
   R6-vs-R5 Recall@10 noninferiority lower 95% bound >= -0.01, and graph mapping-subset
   gain lower 95% bound > 0. Missing comparable labels cannot be turned into a number.
6. Authorization policy, publication recovery and backend isolation are explicit
   release blockers in addition to predecessor correctness, secret handling,
   freshness/lifecycle, matched parity and rollback. High retrieval scores cannot
   override these gates.
7. Rollback restores a retained verified generation by changing the active pointer in
   the current catalog. Current tombstones/revocations remain live; restoring an old
   catalog/database backup is intentionally not the normal rollback mechanism.
8. Readiness statuses are evidence inputs, not self-authorizing test results.
   `ready_for_explicit_promotion` still has automatic_promotion=false and the advanced
   default remains opt-in until the implementation session separately authorizes a
   switch.
9. No cross-repository RuntimePolicy implementation is added. Retrieved evidence and
   graph/retrieval scores cannot grant authority or execute tools.
10. Generic extraction remains deferred until CTI reaches MVP-C, a materially different
    second domain (preferably networking) exists end-to-end, and duplicated shared
    contract implementation is demonstrated in at least two layers.
11. Prompt 22 required Python 3.11 commands are still not_run in this execution
    environment because only Python 3.13.5 is available and the private checkout cannot
    be materialized into the container through the authenticated connector. This is an
    execution limitation, not a pass.


Post-Prompt 22 predecessor-test reconciliation:

1. Target-host Python 3.11 validation exposed two stale Prompt 04/05 assertions that
   conflicted with later accepted contracts rather than with current implementation.
2. The CTI graph-pattern assertion now reflects the Prompt 11 planner contract:
   ordinary `mapping` uses the reviewed two-hop template, while three-hop traversal
   requires the explicit `three_hop_mapping` template. The production graph-pattern
   implementation was not widened or relaxed.
3. The metric serialization assertion now includes
   `annotation_coverage: null`, matching the Prompt 17 `MetricResult` schema. The
   fail-closed rule that unavailable metrics serialize with `value: null` remains
   unchanged.
4. These are compatibility-test reconciliations only; no retrieval, policy, graph
   traversal, or evaluation runtime behavior was changed.


Target-host full-suite reconciliation after Prompt 22:

1. The Python 3.11 focused Prompt 04/05 gate passed 48/48 after the predecessor
   assertion reconciliation.
2. Full offline execution exposed a real chunking bug: domain serialization hints can
   include tuples of typed Pydantic values such as CTI markings. The chunker now
   recursively converts typed/nested field values through JSON-mode primitives before
   canonical JSON encoding; it does not weaken the evidence-store JSON-safety boundary.
3. The historical `TrustedPrincipal is Principal` assertion was stale after the
   authenticated advanced API introduced a canonical principal namespace. The test now
   verifies that `TrustedPrincipal` extends `Principal` and carries that namespace.
4. The old publication revocation test now exercises the Prompt 21
   `LifecycleAuthority` explicit-revocation tombstone path before asserting that a
   retained pinned generation is withdrawn. Persisting a newer revision alone is not
   treated as lifecycle authority.
5. Two Prompt 21 E2E freshness fixtures now use valid deterministic SHA-256 evidence
   and object identifiers, matching the hardened evidence schema instead of bypassing
   it with one-character placeholders.


Dense-policy exclusion reconciliation:

1. The deterministic fixture intentionally includes an AMBER-marked restricted record
   so authorization behavior is exercised alongside public evidence.
2. Dense indexing no longer treats a policy-denied chunk as permission to send it to
   the embedding provider, nor as a reason to abort an otherwise valid generation.
   Denied chunks are omitted before the provider call.
3. The dense artifact records sorted `policy_excluded_chunk_uids`. On reopen, every
   generation chunk must be accounted for exactly once as embedded or policy-excluded;
   overlap, duplicates, or an unaccounted chunk fail closed.
4. Exact/lexical/catalog membership remains complete. Query-time dense candidates are
   still reauthorized for caller egress, so this change does not weaken serving policy.


Lexical-tokenizer punctuation reconciliation:

1. Target-host E2E validation showed that the generic tokenizer retained a trailing
   period in prose tokens (for example `causality.`) because `.` is also allowed
   internally for CTI identifiers, versions and domain-like values.
2. The deterministic tokenizer is versioned to `regex-cti-unicode-v2` and now trims
   terminal dot/colon punctuation while preserving internal separators such as
   `T1059.001`, `4.2` and `restricted.example`.
3. The tokenizer fingerprint was deliberately changed so persisted lexical/chunk
   artifacts built under the prior token semantics cannot be reopened as if they were
   equivalent; reindexing is required.
4. The original E2E query `causality` remains unchanged so the regression verifies
   actual lexical behavior rather than weakening the test.


Legacy compile-gate repair:

1. Target-host Prompt 06/07 validation reached its repository-wide `compileall`
   gate after all scoped Prompt 06/07 tests passed, then failed on the historical
   `tests/test_ner.py` manual probe because it contained an incomplete
   `payload =` assignment.
2. The probe is now syntactically valid and import-safe. It performs no HTTP request
   during pytest discovery or compile validation.
3. Manual execution requires an explicit JSON payload path and supports an optional
   endpoint URL/timeout. The change does not modify the NER endpoint, legacy API
   behavior, advanced retrieval behavior, or validation scope.
