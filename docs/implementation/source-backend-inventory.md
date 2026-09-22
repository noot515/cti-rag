# Phase 0 source and backend inventory

Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`

| Component | Baseline role | Phase 0 disposition |
| --- | --- | --- |
| MySQL 8 | KB metadata/application persistence | Reuse; first independent lexical target is a dedicated FULLTEXT projection, not yet activated. |
| Milvus 2.3.4 | Dense vector retrieval | Retain behind a future SearchPort; legacy random INT64 keys are not canonical evidence identity. |
| Neo4j 5.15 Community | Knowledge graph | Retain only for graph tasks; legacy name-only entity identity is a migration target. |
| Redis 7 | Runtime/session/cache | Derived runtime state only, never canonical evidence identity. |
| RabbitMQ 3.13 | Background tasks | Reuse after idempotency/outbox contracts exist. |
| MinIO | Milvus dependency | Canonical source/object-store semantics deferred to Phase 2. |
| Ollama | Local model serving | Optional ModelPort backend; no contract dependency. |
| Remote model providers | Generation/embedding/reranking | Future explicit processing destinations under policy enforcement. |
| Tavily/web | Optional live search | Not used for Phase 0/B0; future live overlay must remain separate from pinned snapshots. |

Existing repository data includes `benchmark/dataset.xlsx`, `config.yaml`, model material under `models/`, and runtime data roots under `./data`. Phase 0 did not download, rewrite, index, or delete any corpus and did not activate any external source connector.

**Initial lexical choice:** MySQL 8 FULLTEXT, because it is already required by deployment and yields the smallest operational increment toward corpus-wide lexical retrieval independent of dense candidates.

Before activation, verify multilingual/identifier tokenization, source/tenant/access/temporal/tombstone filtering at the backend boundary, deterministic snapshot/generation publication, stable passage/revision keys, rebuild/rollback behavior, and measured recall/latency against alternatives.

Security note: the baseline compose file exposes several backend/admin ports and has weak development credential defaults. These are recorded as confirmed baseline risks but are not modified in Phases 0–1 to avoid unrelated runtime changes.
