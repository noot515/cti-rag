# Advanced RAG V3 implementation status

Updated: 2026-09-17. Prompt 08 documented head / Prompt 09 predecessor: `397f3ba49b94bc93a462b7e09c2f7d51f76bd4c5` on `feat/advanced-08-embedding-provider-contract`. Current stacked branch: `feat/advanced-09-milvus-projection`. Legacy embedding/retrieval/Milvus code, collections, volumes, API/session behavior and the default legacy compose stack remain untouched.

## Prompt 08 - fingerprint-bound embedding provider contract

Prompt 08 added import-inert provider contracts, complete fingerprint identity, strict ID/vector validation, deterministic fixture embeddings, a generation-scoped local dense fixture projection/channel, and trusted destination checks before embedding work. The existing advanced provider configuration was extended rather than replaced, and the predecessor fixture revision label `v1` was preserved. The fixture publication path now publishes exact, lexical and deterministic dense projections together without network access or model downloads.

Focused Prompt 08 sandbox validation:

```text
PYTHONPATH=. python -m pytest tests/unit/retrieval/test_embedding_provider.py tests/unit/retrieval/test_fixture_dense.py -q
12 passed
```

## Prompt 09 - non-destructive isolated Milvus projection

Implemented beside the legacy Milvus path:

- injected `MilvusClient` protocol and validated trusted `MilvusEndpointConfig`; importing advanced Milvus modules does not import `pymilvus` or connect to a service;
- generation-specific advanced collection names derived from an explicit `adv_`-style prefix, scope identity and generation identity; legacy namespaces are rejected and no legacy host/port is inferred as a fallback;
- schema uses manual `chunk_uid VARCHAR(64)` primary key plus domain, scope, object UID, object revision UID, generation ID, manifest hash, embedding fingerprint and finite embedding vector; full evidence remains authoritative in the SQLite evidence catalog;
- UTF-8 byte-length validation occurs before collection creation or write side effects;
- provider fingerprint/dimension/metric are bound to the Prompt 08 embedding provider and Prompt 06 generation receipt; same-dimension wrong providers require reindexing;
- collection creation is non-destructive. Repeated generation ingestion upserts into the same matching generation collection. An existing incompatible collection fails closed; the advanced adapter exposes no drop/recreate method;
- build performs evidence authorization before provider encoding, validates exact embedding output mapping, upserts the generation, flushes and loads, then performs a filtered visibility sentinel read before a projection receipt can verify;
- retrieval prefilters domain, scope, generation and embedding fingerprint, records candidate over-fetch/truncation, and then rechecks every backend hit against authoritative catalog membership plus object revision before returning an untrusted `BackendHit`;
- candidate construction rechecks pinned snapshot identity and caller policy; backend outage becomes an explicit unavailable channel result rather than a fallback to another Milvus host;
- no BM25 or reranking is implemented inside the Milvus adapter;
- optional `Pymilvus23Adapter` imports/connects only when explicitly requested, checks the pinned client version, takes only the trusted advanced endpoint/token environment, uses strong-consistency reads, and intentionally exposes no destructive collection API;
- `benchmark/advanced/configs/services.yaml` is a synthetic/public compatibility profile using `127.0.0.1:19531`, distinct from the legacy default port;
- `deploy/advanced-services.compose.yml` declares a separate `cti-rag-advanced` project with Milvus 2.3.4, etcd 3.5.5 and MinIO, unique internal network/volumes, no host ports for dependencies, and loopback-only Milvus ports. MinIO credentials are mandatory environment placeholders and have no committed defaults;
- `requirements-advanced-services.txt` pins `pymilvus==2.3.7` for the Milvus 2.3.x compatibility family;
- real restricted-evidence ingestion is deliberately blocked from promotion because the default compatibility Compose profile does not yet establish authenticated Milvus users/credentials. The current service profile is for synthetic/public compatibility validation only.

## Prompt 08/09 validation state

Available implementation sandbox: Python 3.13.5. Repository target: Python 3.11.

Focused provider + local dense + fake-Milvus correctness chain:

```text
PYTHONPATH=. python -m pytest \
  tests/unit/retrieval/test_embedding_provider.py \
  tests/unit/retrieval/test_fixture_dense.py \
  tests/unit/indexing/test_milvus_adapter.py -q
24 passed
```

Prompt 09 fake-client unit portion: `12 passed`. The tests cover schema/manual PK behavior, upsert/replay, two scopes, scope/generation filters, stale-revision rejection, over-fetch, UTF-8 overflow, wrong fingerprint, visibility lag, schema collision, query outage, fresh-process import safety, endpoint isolation and server-version mismatch.

Real integration command in the implementation sandbox:

```text
PYTHONPATH=. python -m pytest tests/integration/test_advanced_milvus.py -q -m integration
2 skipped
```

The skips are expected because `ADVANCED_MILVUS_INTEGRATION_URI` and `LEGACY_MILVUS_INTEGRATION_URI` are not configured. Docker is also unavailable in the implementation sandbox, so these commands remain `not_run` here:

```text
docker compose -f deploy/advanced-services.compose.yml config --quiet
docker compose -f deploy/advanced-services.compose.yml up -d advanced-milvus
python -m pytest tests/integration/test_advanced_milvus.py -m integration -q
```

`python -m compileall -q packages benchmark tests scripts` passed locally, and the new YAML files parse successfully. The exact Prompt 08/09 branch has not been rerun under Python 3.11 or through full-repository collection in this partial sandbox. Those gates remain `not_run`; the earlier Prompt 06/07 Python 3.11 gate also remains independently unresolved.

`scripts/validate_advanced_08_09.py` is the fail-fast chained entry point for a clean full Python 3.11 checkout. It verifies the Prompt 08 predecessor, runs the 24 focused unit tests, compile validation and `git diff --check`, then runs Compose validation when Docker exists. Real service startup/integration occurs only when explicitly enabled and configured.

## Release blockers / next-phase readiness

Prompt 09 fake-client mechanics are implemented, but service promotion is blocked until all of the following are observed on the exact stack: Python 3.11 repository validation, `docker compose ... config --quiet`, successful isolated Milvus 2.3.4 startup with PyMilvus 2.3.7, real advanced roundtrip integration, proof that the configured legacy endpoint cannot see the advanced collection, and an authenticated advanced-service configuration before any restricted evidence is allowed. No retrieval-quality claim is made from deterministic fixture embeddings or fake-client tests.
