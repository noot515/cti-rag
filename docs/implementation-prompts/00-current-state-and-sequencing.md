# Current state and sequencing handoff

Prompt 16 begins from Prompt 15 documented head `66075304be97c6234d7863cf186d97f51ce16776` on `feat/advanced-15-trusted-principal-and-corpus-access` and is stacked on `feat/advanced-16-authenticated-advanced-api`.

Reconciliation notes:

1. Prompt 15 remains the identity/grant authority. Prompt 16 does not accept body principals, legacy `User.user_id`, or legacy knowledge-database ownership.
2. The direct FastAPI application route is `/chat/advanced-retrieval`; any external `/api` prefix is owned by a reverse proxy/gateway and is not silently assumed by application routing.
3. `rag.api.routers.__init__` no longer imports chat/data/graph/token routers at package-import time. Legacy callers retain `from rag.api.routers import router` through lazy `__getattr__` assembly.
4. The module-level legacy `fastapi_server` still mounts only legacy routes. `create_fastapi_server(advanced_router=...)` is the narrow opt-in extension point; `config.yaml` records advanced disabled by default.
5. `create_advanced_router()` returns an empty router when the validated advanced config is disabled. Enabled construction may use the existing JWT-backed authenticated-user dependency, but fixture applications inject identity and therefore avoid importing the legacy MySQL-backed auth stack.
6. Request shape is strict/extra-forbid: query, db_id, top_k, max_graph_hops, response_mode and omitted/false web_search only. UTF-8 query bytes, top_k and hop count are bounded.
7. Authentication and `CorpusAccessStore.resolve_scope()` occur before `runtime_provider()` is called. A denied tenant/corpus therefore makes zero advanced backend/provider calls.
8. `response_mode=full` is not itself authority. The server-owned `evidence:debug` capability is independently required, and debug candidates pass a final candidate-authorizer callback.
9. The runtime finalizer is called immediately before API serialization. This is in addition to Prompt 14's post-pack evidence re-resolution and closes the route-level withdrawal/grant-change boundary.
10. Successful empty evidence maps to HTTP 200 `no_evidence`; all-channel unavailability maps to 503; malformed input remains 422; unknown/unauthorized corpus stays indistinguishable 403; no failure delegates to legacy retrieval.
11. Responses expose context/citations/status/telemetry/model fingerprints, not a generated answer. Scores/paths remain retrieval evidence rather than truth probabilities.
12. `create_fixture_app()` is service-inert on import and accepts injected local exact/lexical/dense/catalog-graph runtime pieces. Fixture configuration forbids outbound networking/downloads/web search/service Milvus.
13. Fresh-process tests assert importing `rag.api.advanced_app` does not import legacy chat/data/graph/token routers or the legacy DB manager.
14. Exact Prompt 16 ASGI/import-safety execution is still a Python 3.11 target-environment gate because this sandbox lacks the pinned advanced API environment. No unrun gate is marked passed.
15. Prompt 17 may evaluate native retrieval/API outputs from this boundary. It must not ablate authorization, tune held-out labels, or convert fixture-only mechanics into a quality-promotion claim.
