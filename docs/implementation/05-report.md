# Phase 05 implementation report — exact lookup and persistent independent lexical retrieval

Status: **implementation/own gate passed; production activation blocked by inherited Phase 0 gates and real MySQL FULLTEXT service validation**

## Lineage and fingerprints

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/04-report.md`
- Phase 04/05 code checkpoint: `9c67c4012c4e8810ef4087d3eeb6b928f0b0165b`
- Config blob: `a90848b9f9884c344d3fe2cc10cd6ec8c13da591`
- Baseline corpus blob: `5820fa64bed3db3147d52d632975a21101893bff`
- Baseline model blob: `b06a0a7f5e5209553993045009c4e878b54a6435`
- Exact implementation blob: `d75a94c74ccbfd2afbc48da3a35d888d64c009af`
- SQLite lexical implementation blob: `cc93b56164df9b84e7909374f2f66cc691bd1a62`
- MySQL lexical implementation blob: `7ef3a1f7c3be68f3c2e58210179bfd1e4ff678e0`
- Phase 05 test blob: `b96a15e0484a87b450604e601d45c82b2fa85e2b`
- No semantic model was invoked; the lexical integration fixture is deterministic and offline.

## Implemented

A deterministic identifier registry handles CVE, CWE, ATT&CK technique, ASN, CIDR, DOI, RFC, and ISBN namespaces, with extension hooks for later domain identifiers. Exact lookup canonicalizes through the namespace parser, enforces object type, authorized tenant/domain/access/source scope, availability cutoff, optional validity interval, pinned manifest generation, and the current revocation overlay. Wrong-ID near matches are not fuzzy-matched. Multiple logical objects for one canonical identifier return `ambiguous`; multiple eligible revisions of one object select the latest eligible source revision deterministically.

Canonical exact records are a separate projection from passage text. A report that mentions a CVE can be retrieved lexically but cannot become the canonical CVE exact record unless its projected identity is actually a CVE object.

`StructuredJsonProjector` produces structure-aware JSON-pointer passages, exact keyword records, immutable source locators, original quotation text, separately normalized search text, deterministic context prefixes, and a versioned analyzer identifier.

Two persistent lexical adapters now implement the same snapshot/scope contract:
- `MySQLFullTextLexicalIndex`: production-candidate MySQL 8 FULLTEXT projection using the existing configured engine/pool; no new credential path.
- `SQLiteFTS5LexicalIndex`: persistent local/CI backend used for an actual full-text integration test.

Lexical search is independent of dense candidates, generation-selected from the pinned manifest, persistent across adapter restart, deterministic by backend score then passage UID, and filters tenant/domain/access/source/temporal eligibility and current tombstones inside the retrieval boundary. Rebuilding the same immutable generation is idempotent. Returned passages contain locators pointing to the indexed revision.

## Validation actually executed

Final GitHub Actions run `35740638328`, job `106789187458`, completed successfully on Python 3.13.15.

Cumulative result: **55/55 passed in 1.037 s**, including **11 Phase 05 exact/lexical tests**.

The actual SQLite FTS5 integration test created an on-disk FTS5 database, indexed a passage whose distinguishing terms were absent from the supplied dense candidate set, retrieved it independently, destroyed/recreated the adapter against the same database file, and retrieved the same citable passage after restart.

Phase 05 acceptance fixtures passed:
- independent lexical retrieval finds the dense-missing passage;
- persistence survives backend restart;
- exact lookup rejects malformed/wrong near identifiers and reports object ambiguity;
- exact selection excludes a future revision and respects an explicit validity interval;
- a report mentioning an identifier is not treated as its canonical exact record;
- private and future records do not leave the backend;
- historical-public cutoff is enforced inside exact and lexical boundaries;
- reindexing an existing immutable generation is idempotent;
- current tombstones hide passage and revision results even through the old pinned snapshot;
- returned locator `/summary` resolves to the indexed source revision;
- registry hooks cover cyber, networking, and humanities identifier types.

## Production-backend blocker

The MySQL FULLTEXT adapter is implemented but **not accepted as production-ready**. No reachable service-complete MySQL runtime was available to execute its real analyzer, FULLTEXT behavior, security/temporal filters, publication visibility, rebuild/rollback, delete cleanup, or representative latency/recall. This is recorded as a required blocked gate. The successful SQLite FTS5 integration does not convert that MySQL gate into a pass.

Milvus BM25 was not claimed as compatible because the repository pins an older Milvus deployment and no real capability test established the required analyzer/filter/publication contract.

## Migration, rollback, and handoff

No legacy candidate-only BM25 behavior was removed and no new retrieval route was activated. MySQL tables are created only if the adapter is explicitly constructed against the configured manager.

Independent next-phase work can proceed from the exact/lexical/snapshot interfaces. Production serving/promotion should remain disabled until the inherited Phase 0 service/B0 gates and the real MySQL FULLTEXT service gate pass.
