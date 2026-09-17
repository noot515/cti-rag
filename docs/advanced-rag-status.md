# Advanced RAG V3 implementation status

Updated: 2026-09-17. Prompt 15 documented head / Prompt 16 predecessor: `66075304be97c6234d7863cf186d97f51ce16776`. Current stacked branch: `feat/advanced-16-authenticated-advanced-api`. Legacy retriever/data/session routes remain available and advanced retrieval is still default-disabled.

## Prompt 14 - evidence packing and citations

Prompt 14 provides terminal token-budgeted evidence packing after final candidate ordering. Response-local citations preserve exact evidence/revision/scope/snapshot/source coordinates; paths are indivisible node/assertion/support bundles; untrusted evidence text cannot execute tools; and selected evidence is resolved/authorized again before response egress.

Focused local compatibility gate: `10 passed`. Combined locally feasible Prompt 12-14 mechanics: `42 passed`.

## Prompt 15 - trusted identity and corpus grants

Prompt 15 establishes canonical namespaced `User.id` principals, the separate `CorpusAccessStore`, server-owned corpus/domain/scope/catalog/policy grants, mid-query grant revalidation, fail-closed 401/403/503 mapping, pinned python-jose handling and trusted local corpus registration. Legacy `User.user_id` and caller-populated `KnowledgeDatabase.user_id` do not grant advanced access.

Dependency-free local access/identity core: `7 passed`. Combined locally feasible Prompt 12-15 mechanics/core: `49 passed`. Full JOSE token execution remains target-environment validation because the sandbox cannot install packages.

## Prompt 16 - isolated authenticated advanced API

Prompt 16 adds an opt-in advanced HTTP surface without replacing the legacy application:

- `rag.api.routers.advanced_retrieval_api.create_advanced_router()` creates the direct `POST /chat/advanced-retrieval` route only when an already validated `AdvancedRagConfig` is enabled;
- the request accepts only `query`, `db_id`, bounded `top_k`, bounded `max_graph_hops`, `response_mode`, and omitted/false `web_search`. Pydantic forbids caller principal/policy/backend/filter fields and `web_search=true`; the query is additionally bounded to 8192 UTF-8 bytes;
- trusted identity and server-owned corpus grant resolution run before the runtime provider is invoked, so a denied request cannot construct/use retrieval backends or model providers;
- `response_mode=full` separately requires the server-owned `evidence:debug` capability. Debug candidates are emitted only through a final candidate-authorizer callback;
- the runtime executes a final result reauthorization/finalization callback immediately before serialization, after Prompt 14's packed-evidence recheck;
- successful empty retrieval returns HTTP 200 with `status=no_evidence`; all-channel unavailability returns 503; identity is 401; unknown/unauthorized corpus is indistinguishable 403; malformed/extra request fields remain FastAPI 422; there is no legacy fallback;
- responses expose retrieval context, citations, channel states, degraded channels, truncation, timings and model fingerprints, not a generated answer;
- `rag.api.routers.__init__` now assembles legacy routers lazily. Importing the advanced submodule no longer imports legacy chat/data/graph/token routers or the MySQL manager first;
- `rag.api.server.create_fastapi_server()` preserves the module-level legacy `fastapi_server` with no advanced router by default. `config.yaml` records `advanced_rag.enabled: false` and the direct path/proxy distinction;
- `rag.api.advanced_app.create_fixture_app()` builds an advanced-only application with injected identity/access/runtime pieces. Fixture configuration requires no outbound networking, no service Milvus and no legacy MySQL/Redis/RabbitMQ/GPU construction at import time;
- `docs/advanced-rag-api.md` documents the direct URL, request/response contract, feature flag, error semantics and fixture application.

### Prompt 16 target validation

Required target commands:

```text
python -m pytest tests/unit/api/test_advanced_route.py tests/e2e/test_advanced_api.py -q
python -m pytest tests/unit/evidence/test_imports.py -q
```

The committed tests cover disabled 404 behavior, unknown authority fields, web-search rejection, independent debug permission, successful/empty/partial/all-down responses, cross-tenant denial before backend calls, final withdrawal/finalizer execution, and a fresh-process import check that asserts legacy service routers/managers are absent.

These exact commands remain `not_run` in the implementation sandbox because the intended Python 3.11 advanced API environment (including pinned FastAPI/httpx/python-jose) is unavailable here. No target-environment pass is inferred from code publication.

## Chained validation

`scripts/validate_advanced_04_15.py` remains the strict predecessor Python 3.11 chain. Prompt 17 will extend the handoff through Prompt 16 and native evaluation rather than replacing the unresolved predecessor gates.

## Remaining operational/quality gates

- exact Python 3.11 Prompt 04+ chain with `requirements-advanced-dev.txt` installed;
- full repository collection on the final descendant;
- real Milvus/Neo4j roundtrip and legacy-isolation gates;
- deployment wiring of the enabled protected route and operator signing authority;
- production restricted-marking policy;
- real reranker/generator/judge compatibility and retrieval-quality/promotion gates.

## Handoff

Prompt 16 correctness contracts are implemented on top of Prompt 15. Prompt 17 may evaluate the native advanced route/retrieval outputs, but fixture mechanics cannot be promoted into a real-quality claim and authorization must never be ablated.
