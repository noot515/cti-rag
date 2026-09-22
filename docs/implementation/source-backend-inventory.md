# Phase 0 source and backend inventory

Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`

| Component | Baseline role | Current evidence-runtime disposition |
| --- | --- | --- |
| MySQL 8 | KB metadata/application persistence | Reused for the production-candidate exact and independent FULLTEXT projections through the existing configured engine/pool. Adapter implemented; real-service validation remains blocked and the route is not activated. |
| SQLite FTS5 | Not a baseline service | Added as an isolated persistent local/CI lexical integration backend. Actual FTS5 restart, filtering, snapshot-generation, idempotency, locator, and tombstone tests pass; this does not substitute for MySQL service readiness. |
| Milvus 2.3.4 | Dense vector retrieval | Retain behind a future SearchPort; legacy random INT64 keys are not canonical evidence identity. No Milvus BM25 production claim was inferred from documentation. |
| Neo4j 5.15 Community | Knowledge graph | Retain only for graph tasks; legacy name-only entity identity is a migration target. Future graph generations must bind to the same manifest revision set as other enabled projections. |
| Redis 7 | Runtime/session/cache | Derived runtime state only, never canonical evidence identity. Revocation now defines explicit cache-invalidation events. |
| RabbitMQ 3.13 | Background tasks | Reuse after idempotency/outbox contracts exist; projection generation publication remains controlled by the metadata catalog, not queue acknowledgment. |
| MinIO | Milvus dependency | Not used as canonical identity authority. Canonical object-storage semantics are implemented separately and remain explicit. |
| Ollama | Local model serving | Optional ModelPort backend; no contract dependency. |
| Remote model providers | Generation/embedding/reranking | Explicit processing destinations under policy enforcement. |
| Tavily/web | Optional live search | Not used for baseline/B0 or Phase 04/05 acceptance; future live overlay must remain separate from pinned snapshots. |

Existing repository data includes `benchmark/dataset.xlsx`, `config.yaml`, model material under `models/`, and runtime data roots under `./data`. Phases 00–05 did not activate the new retrieval route or mutate the live legacy corpus/indexes.

**Production lexical choice remains MySQL 8 FULLTEXT.** The adapter now has generation IDs, snapshot selection, exact security/temporal filters, deterministic ordering, restart persistence by database design, and tombstone filtering in its query boundary. It is not production-ready until the actual MySQL service is exercised for analyzer behavior, filters, publication visibility, rebuild/rollback, delete handling, and representative performance.

**Actual integration evidence available today:** SQLite FTS5 executed in GitHub Actions with persistent on-disk state. A relevant passage absent from any supplied dense candidate set is retrieved lexically, survives adapter restart, is filtered by tenant/domain/access/time, and becomes inaccessible after tombstoning.

Security note: baseline compose exposure and weak development credential defaults remain recorded baseline risks and were not modified as unrelated work.
