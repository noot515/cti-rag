# Phase 0 source and backend inventory

Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`

| Component | Baseline role | Current evidence-runtime disposition |
| --- | --- | --- |
| MySQL 8 | KB metadata/application persistence | Reused for the production-candidate exact and independent FULLTEXT projections through the existing configured engine/pool. Adapter implemented; real-service validation remains blocked and the route is not activated. |
| SQLite FTS5 | Not a baseline service | Added as an isolated persistent local/CI lexical integration backend. Actual FTS5 restart, filtering, snapshot-generation, idempotency, locator, and tombstone tests pass; this does not substitute for MySQL service readiness. |
| Milvus 2.3.4 | Dense vector retrieval | Legacy random-INT64 behavior is preserved. A new `MilvusDenseSearchPort` creates fingerprint-separated compatible collections with deterministic VARCHAR passage IDs, snapshot/scope/temporal/revocation filtering, and canonical hydration. Real Milvus publication/delete/restart/ANN-recall validation remains blocked. |
| Deterministic in-memory dense oracle | Not a baseline service | Added only for exhaustive-search and contract validation. It exercises embedding-space identity, filtered eligibility, revocation, query-fingerprint compatibility, and ANN-vs-exhaustive measurement mechanics. It is not semantic-quality evidence. |
| Neo4j 5.15 Community | Knowledge graph | Retain only for graph tasks; legacy name-only entity identity is a migration target. The Phase 07 planner emits graph nodes only when a graph capability is installed and otherwise records an explicit evidence gap. |
| Redis 7 | Runtime/session/cache | Derived runtime state only, never canonical evidence identity. Revocation defines explicit cache-invalidation events. Dense embedding cache isolation additionally includes tenant/access/processing namespace plus the full embedding fingerprint. |
| RabbitMQ 3.13 | Background tasks | Reuse after idempotency/outbox contracts exist; projection generation publication remains controlled by the metadata catalog, not queue acknowledgment. |
| MinIO | Milvus dependency | Not used as canonical identity authority. Canonical object-storage semantics are implemented separately and remain explicit. |
| Ollama / local embedding runtime | Local model serving | ModelPort-compatible destination. Dense mechanics are implemented, but the repository's actual embedding model was not loaded in offline CI; the real-model gate remains blocked. |
| Remote model providers | Generation/embedding/reranking | Explicit processing destinations under policy enforcement. Provider authorization occurs before uncached text is assembled or dispatched. The Phase 08 reranker is centrally owned and receives only authorized hydrated passages; real reranker-model acceptance remains blocked. |
| DuckDB | Not a baseline service | Added as the structured analytical engine. CI executes a real DuckDB runtime over server-preloaded fixture tables with external access/unsigned extensions disabled and memory/thread/scan/time bounds. Typed query compilation, temporal revision selection, units/nulls, lineage, aggregation semantics, and IP containment pass. |
| Advanced evidence API | Not a baseline endpoint | `POST /research/advanced-retrieval` is additive, evidence-only, dependency-injected, authenticated, and disabled by default behind `CTI_RAG_ADVANCED_RETRIEVAL_ENABLED`. Existing chat/data endpoints remain the default legacy route. |
| Tavily/web | Optional live search | Not used for baseline/B0 or Phase 04–07 acceptance; any future live overlay must remain separate from pinned snapshots. |

Existing repository data includes `benchmark/dataset.xlsx`, `config.yaml`, model material under `models/`, and runtime data roots under `./data`. Phases 00–09 did not activate the new retrieval route or mutate the live legacy corpus/indexes.

**Production lexical choice remains MySQL 8 FULLTEXT.** The adapter has generation IDs, snapshot selection, security/temporal filters, deterministic ordering, and tombstone filtering, but the real MySQL service still requires execution evidence.

**Dense migration strategy:** do not rewrite the legacy KnowledgeBase collection in place. Build new compatible Milvus generations keyed by deterministic passage UID, publish them only through the shared snapshot catalog, and keep incompatible embedding fingerprints physically/logically separate.

**Actual integration evidence available today:** SQLite FTS5 executes persistently in GitHub Actions; DuckDB executes as a real analytical engine over preloaded registered tables. The Phase 08 synthetic end-to-end fixture runs source ingestion → canonical objects → published exact/lexical indexes → planning/retrieval → canonical hydration → reranking → tokenizer-bounded context/citation verification → evidence response. Dense semantic quality, real Milvus lifecycle/ANN behavior, actual reranker quality, and the actual configured generator tokenizer remain explicit external gates.

Security note: baseline compose exposure and weak development credential defaults remain recorded baseline risks and were not modified as unrelated work.
