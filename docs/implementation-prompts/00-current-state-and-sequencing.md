# Current state and sequencing handoff

Prompt 06 begins from Prompt 05 documented head `ea127277f4fdade1aa66ee21d0ad37bc78f7d3c3` on `feat/advanced-05-durable-evidence-catalog` and is stacked on `feat/advanced-06-snapshot-publication`. Prompt 06 implementation code reached `38afbfdb08356fcb279d0bb855bcff471cb0af09` before documentation commits.

Reconciliation notes:

1. Prompt 05 already owns durable inactive snapshots and revision membership. Prompt 06 reuses those tables instead of creating a second evidence catalog.
2. Publication-specific state uses opt-in `packages/evidence/publication_migrations.py`, applied only when `SnapshotCatalog` is constructed. This preserves the Prompt 05 catalog `user_version` and avoids changing storage behavior for callers that never enable publication.
3. `GenerationManifest` is deterministic and immutable over domain/scope/corpus, exact revision membership, projection configuration and fingerprints. Disabled optional channels are explicit manifest entries.
4. `PublicationOrchestrator` registers the generation and durable projection jobs before any backend writer runs. Prompt 06 tests use fake projection writers only.
5. A projection receipt must match generation, domain, scope, corpus, manifest hash, membership hash/count and projection fingerprint, and must pass a visibility sentinel check. Verified receipts are immutable.
6. Generation state advances `building -> ready -> active` only after every enabled projection verifies. Required failure leaves the new generation inactive and retains the old active pointer.
7. Activation updates the active pointer in one catalog transaction. The pointer is unique per `(domain, scope_id, corpus_id)`; different corpora in one scope remain independent.
8. `SnapshotHandle` pins one generation for its lifetime. Publication never switches a pinned request mid-flight and never repurposes or drops the old generation.
9. Revocation/deletion remains a live overlay: an older pinned handle is denied if the logical evidence is later withdrawn.
10. Restart recovery reconciles all-receipt, ready, and post-activation/pre-ack crash windows from durable manifest/receipt/pointer state. A partial receipt set remains building and inactive.
11. Legacy `packages/core/knowledgebase.py` and its destructive collection behavior are unchanged; advanced publication exists beside it.
12. Prompt 07 may build exact/lexical projection writers on these contracts. Real Milvus/Neo4j atomicity, distributed transactions, incremental reuse, deployment and promotion remain future/non-goals.

Validation state: the Prompt 06 focused sandbox suite passed (`14 passed`) under Python 3.13.5. Repository target Python 3.11, full-repository collection, real-service compatibility and quality gates remain `not_run` on this exact stack and must not be inferred from predecessor results.
