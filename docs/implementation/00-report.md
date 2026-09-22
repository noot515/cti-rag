# Phase 0 implementation report — actual repository baseline

Status: **implemented; acceptance blocked by unexecuted legacy runtime gates**

## Baseline

- Repository: `noot515/cti-rag`
- Default branch: `main`
- Baseline commit: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Baseline commit date: 2026-09-15T06:34:19Z
- The historical plan SHA matches the actual current `main` baseline; it was verified, not assumed.
- No `.github/` CI directory was present at baseline.
- `pytest.ini` discovers `*_test.py`.
- New retrieval remains disconnected from the legacy runtime and is disabled.

## Verified inherited claims

| Claim | Status | Baseline evidence |
| --- | --- | --- |
| Candidate-only BM25 | confirmed | `packages/core/knowledgebase.py` trains BM25 from dense `db_result` candidates before `HybridRetriever.hybrid_search`. |
| Random Milvus IDs | confirmed | `KnowledgeBase.add_documents` writes `int(random.random() * 1e12)` to the INT64 primary key. |
| Name-based graph identity | confirmed | `packages/core/graphbase.py` uses `MERGE (a:Entity {name: $h})` / `MERGE (b:Entity {name: $t})`. |
| Graph flattening | confirmed | `packages/core/retriever.py` converts graph edges to strings before reranking. |
| Duplicate reranking ownership | confirmed | Both `KnowledgeBase` and `Retriever` initialize rerankers; the hybrid path can rerank before application reranking. |
| Provider coupling | confirmed | `packages/config/__init__.py` forces unsupported/non-DeepSeek main-path providers back to `deepseek`. |
| Exposed backend/admin ports | confirmed | Compose publishes MySQL, Redis, RabbitMQ, Neo4j, MinIO, Milvus, Ollama, and API ports. |
| Weak credential defaults | confirmed | Compose/core/database configuration includes defaults such as `12345678`, `guest`, and `minioadmin`. |

## Fingerprints and runtime inventory

Baseline blobs include `benchmark/dataset.xlsx` = `5820fa64bed3db3147d52d632975a21101893bff`, `config.yaml` = `a90848b9f9884c344d3fe2cc10cd6ec8c13da591`, `requirements-api.txt` = `13f016ec417905a096950fba76bcfc570d464fb6`, `docker-compose.yml` = `d38dc805c375598165a7cffdd0642b76e015f1b9`, and `models/neo4j_final_agent.pt` = `b06a0a7f5e5209553993045009c4e878b54a6435`.

Primary entry points are `main.py` and `rag/api/server.py`; background workers live under `rag/mq/`. The deployed stack includes MySQL 8, Redis 7, RabbitMQ 3.13, Neo4j 5.15 Community, Milvus 2.3.4 with etcd/MinIO, and Ollama.

## Lexical backend decision

The initial production-compatible target is a dedicated **MySQL 8 FULLTEXT projection** because MySQL is already in the pinned stack. This adds no new service and can be a rebuildable derived index independent of dense retrieval. Activation remains deferred until analyzer, authorization/temporal filtering, snapshot publication, rebuild/rollback, and retrieval-quality checks are complete.

## Validation actually executed

```text
python -m unittest tests.contracts_phase1_test tests.validation_runner_test -v
```

Result: **17/17 passed**. Local validation environment: Python 3.13.5, Linux 6.18.44 x86_64. Measured run: 5.07 s wall time and 94,252 KB maximum resident set size.

The cumulative runner was executed through Phase 1 and returned exit code 1 by design: the required legacy Phase 0 fast-suite and B0 benchmark gates are explicitly `blocked`. Missing prerequisites were not converted into passes.

### Blocked required gates

- Legacy fast/full runtime suite: **blocked** because a service-complete isolated checkout with its runtime dependencies was not available in this connector execution.
- B0 offline benchmark: **blocked** because the legacy benchmark calls the running API/model stack and no pinned local service/corpus stack was available. No remote model or search call was substituted.

All Phase 0/1 changes are additive; no live index, user data, schema, or service configuration was changed.
