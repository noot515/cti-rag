# Advanced RAG implementation prompt status

This directory tracks implementation-state handoffs, not the full external prompt pack.

- Prompt 01: predecessor accepted on stacked branch `feat/advanced-01-offline-foundation` at `312e11837bde5b525d277bf7387c57ce30487bb3`.
- Prompt 02/03: implemented and later validated on Windows/Python 3.11, including full repository collection at that stack.
- Prompt 04/05: implemented; focused sandbox gates passed, but their exact later Python 3.11 chain remains tracked separately.
- Prompt 06: implemented on `feat/advanced-06-snapshot-publication`; focused publication/recovery sandbox gate passed (`14 passed`).
- Prompt 07: implemented/documented on `feat/advanced-07-chunk-exact-lexical`; exact full-checkout Python 3.11 chain remains separately unresolved.
- Prompt 08: implemented/documented on `feat/advanced-08-embedding-provider-contract`; focused sandbox gate passed (`12 passed`).
- Prompt 09: implemented/documented on `feat/advanced-09-milvus-projection` at `b76830493d41bb0b6931187ffbd8a406299aedb3`; combined Prompt 08/09 offline gate passed (`24 passed`), while real Milvus service/isolation remained separate.
- Prompt 10: implemented/documented on `feat/advanced-10-neo4j-evidence-projection` at `1667ddb1d155412a46fa86c3c17acef30d76da54`; focused local mechanics passed (`15 passed`), real Neo4j service/isolation separate.
- Prompt 11: implemented/documented on `feat/advanced-11-deterministic-query-planner` at `86593709fff8bab1b7b0153b1bad32f86ed3b651`; focused planner/target passed (`18 passed`), combined Prompt 10/11 mechanics (`33 passed`).
- Prompt 12: implemented/documented on `feat/advanced-12-fusion-and-orchestration` at `358be5665a6d124bad5c5f01c794fe898ff30afb`; final descendant P12 mechanics passed `15` local tests.
- Prompt 13: implemented/documented on `feat/advanced-13-single-final-reranker` at `73a0429dc7de58714148197172f9fffb68baf052`; focused local gate `17 passed`, combined P12/13 `32 passed`.
- Prompt 14: implemented/documented on `feat/advanced-14-evidence-packing` at `65701c1885ead1901e0f84c95227a1ced25190e2`; focused local gate `10 passed`, combined P12-14 `42 passed`.
- Prompt 15: implemented/documented on `feat/advanced-15-trusted-principal-and-corpus-access` at `66075304be97c6234d7863cf186d97f51ce16776`; canonical namespaced identity/server-owned grant mechanics are present. Dependency-free local core passed `7`; full JOSE token tests remain target-environment validation.
- Prompt 16: implemented on `feat/advanced-16-authenticated-advanced-api` from Prompt 15 head `66075304be97c6234d7863cf186d97f51ce16776`; default-disabled isolated route factory, lazy legacy router assembly, advanced-only fixture app, strict request contract, grant-before-runtime ordering, independent debug permission, final pre-serialization callback and structured API status/egress behavior are present. Exact Python 3.11 ASGI/import-safety exit commands remain target-environment validation.

`scripts/validate_advanced_04_15.py` is the strict predecessor Python 3.11 correctness handoff. Prompt 17 extends validation through Prompt 16 and native evaluation while retaining all unresolved predecessor gates as explicit prerequisites rather than implied success.
