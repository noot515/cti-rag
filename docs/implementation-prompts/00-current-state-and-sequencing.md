# Current state and sequencing handoff

Prompt 07 begins from Prompt 06 documented head `fb9a816ac083741fcce245c4e0b02fbd001e7c6e` on `feat/advanced-06-snapshot-publication` and is stacked on `feat/advanced-07-chunk-exact-lexical`. Prompt 07 implementation/hardening reached `d59673c2fea84373d46b706a6786ea39d9bbe778` before this documentation commit.

Reconciliation notes:

1. Prompt 06 is the publication authority. Prompt 07 does not add another active-pointer mechanism; exact and lexical writers satisfy the existing `ProjectionWriter`/`ProjectionReceipt` contract and activation still occurs only through `PublicationOrchestrator`/`SnapshotCatalog`.
2. Prompt 05/06 generation membership is represented by `snapshots` plus `snapshot_membership`. Exact and lexical artifacts are built from that pinned membership rather than from legacy file IDs or per-query dense candidates.
3. Legacy `packages/core/indexing.py`, `packages/core/bm25_retriever.py`, `packages/utils/bm25.py`, legacy collections and legacy API/session behavior remain unchanged. Prompt 07 owns a separate advanced deterministic tokenizer/chunker and persistent BM25 artifact.
4. `DeterministicTokenizer` preserves whole CVE/CWE/CAPEC/ATT&CK identifiers. `ChunkingConfig` defaults to 450 target tokens and 75 overlap and rejects invalid budgets. Chunk identity remains revision-bound through the Prompt 03 `chunk_uid` contract.
5. CTI field serialization hints determine deterministic section order. Chunk source offsets are stored in an `EvidenceExtension`; CTI-specific marking/citation fields are populated without moving authorization into the domain adapter.
6. Exact identity is restricted to canonical external identifiers, source identities and STIX IDs. Alias candidates and body text are deliberately excluded from exact indexing.
7. Lexical indexing is full-generation persistent BM25, not BM25 over dense candidates. Validated tokenization/DF/length state is serialized as JSON and revalidated against catalog chunk text when reopened; untrusted pickle is not used.
8. Exact/lexical backend hits remain untrusted until policy/candidate construction. Lexical text hydration rechecks scope, generation membership, tombstones/lifecycle and policy authorization.
9. Exact and lexical projection receipts carry the full generation membership count/hash because Prompt 06 receipts describe generation publication, while backend artifacts themselves verify their own relevant object/chunk coverage and artifact sentinel.
10. Fixture configuration explicitly enables exact/lexical and disables dense/graph. The fixture CLI requires a trusted local principal, explicit source allowlist, offline network flags, a manifest under `tests/fixtures/cti`, and a matching `objects.jsonl` SHA-256. Query/qrel/annotation roles are not accepted through the corpus manifest.
11. A no-change ingest rebuild may rewrite the same content-addressed JSON artifacts but retains the same generation and produces no logical catalog changes. A changed object revision produces new revision-bound chunks; old chunks remain immutable historical catalog rows but are absent from the new generation membership.
12. `scripts/validate_advanced_06_07.py` is the required chained validation entry point for this implementation session. It requires Python 3.11 and fail-fast chains both P06 and P07 tests, fixture CLI ingest, `compileall`, and `git diff --check` in one command.
13. The current sandbox is Python 3.13.5 and only has a partial local scratch workspace, so the exact full-checkout P07/chained Python 3.11 gate is `not_run`. A local compatibility harness using the actual P06 manifest/receipt shape passed and the new modules/tests compile, but those results do not substitute for the repository exit gate.
14. Prompt 08 should not be treated as unblocked until `python scripts/validate_advanced_06_07.py` passes on a clean/full Python 3.11 checkout. Real-service publication/deployment remains blocked independently.

Validation state: Prompt 06 focused sandbox suite passed (`14 passed`). Prompt 07 local compatibility harness reported `LOCAL_P07_INTEGRATION_OK 1 1 1`; module/test `py_compile` passed. The strict chained validator correctly refused Python 3.13.5. Exact P07 full-checkout tests, full repository collection, real-service compatibility and quality gates remain `not_run`.
