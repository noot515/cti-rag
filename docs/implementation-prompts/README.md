# Advanced RAG implementation prompt status

This directory tracks implementation-state handoffs, not the full external prompt pack.

- Prompt 01: predecessor accepted on stacked branch `feat/advanced-01-offline-foundation` at `312e11837bde5b525d277bf7387c57ce30487bb3`.
- Prompt 02/03: implemented and later validated on Windows/Python 3.11, including full repository collection at that stack.
- Prompt 04/05: implemented; focused sandbox gates passed, exact later Python 3.11 chain tracked separately.
- Prompt 06: implemented on `feat/advanced-06-snapshot-publication`; focused publication/recovery gate `14 passed`.
- Prompt 07: implemented/documented on `feat/advanced-07-chunk-exact-lexical`; exact later Python 3.11 chain remains tracked.
- Prompt 08: implemented/documented on `feat/advanced-08-embedding-provider-contract`; focused sandbox gate `12 passed`.
- Prompt 09: implemented/documented on `feat/advanced-09-milvus-projection` at `b76830493d41bb0b6931187ffbd8a406299aedb3`; combined Prompt 08/09 offline gate `24 passed`; real Milvus separate.
- Prompt 10: implemented/documented on `feat/advanced-10-neo4j-evidence-projection` at `1667ddb1d155412a46fa86c3c17acef30d76da54`; focused local mechanics `15 passed`; real Neo4j separate.
- Prompt 11: implemented/documented on `feat/advanced-11-deterministic-query-planner` at `86593709fff8bab1b7b0153b1bad32f86ed3b651`; focused planner/target `18 passed`, combined Prompt 10/11 `33 passed`.
- Prompt 12: implemented/documented on `feat/advanced-12-fusion-and-orchestration` at `358be5665a6d124bad5c5f01c794fe898ff30afb`; final descendant P12 mechanics `15 passed` locally.
- Prompt 13: implemented/documented on `feat/advanced-13-single-final-reranker` at `73a0429dc7de58714148197172f9fffb68baf052`; focused local `17 passed`, combined P12/13 `32 passed`.
- Prompt 14: implemented/documented on `feat/advanced-14-evidence-packing` at `65701c1885ead1901e0f84c95227a1ced25190e2`; focused local `10 passed`, combined P12-14 `42 passed`.
- Prompt 15: implemented/documented on `feat/advanced-15-trusted-principal-and-corpus-access` at `66075304be97c6234d7863cf186d97f51ce16776`; canonical namespaced identity/server-owned grant mechanics are present. Dependency-free local core passed `7`; full JOSE token tests remain target-environment validation.
- Prompt 16: implemented/documented on `feat/advanced-16-authenticated-advanced-api` at `1b0e03fc3a54367cb0930318db6477a2667b8e02`; default-disabled isolated advanced route, lazy legacy-router assembly, fixture-only app, strict request contract, grant-before-runtime ordering, independent debug permission and final pre-serialization callback are present. Exact Python 3.11 ASGI/import-safety exits remain target-environment validation.
- Prompt 17: implemented on `feat/advanced-17-native-evaluation-and-ablations`; implementation/test head before final handoff documentation is `9fd83dc85c4575f3ef6518940449a0d93af494e5`. It contains deduplicated target metrics, complete-path/citation/unanswerable contracts, grouped split hashes, deterministic cluster bootstrap, R1-R6/C1 ablation matrix, label-blind fixture retrieval execution, complete report bundles, mapping-subset graph-gain handling, secret-safe config snapshots and honest null quality/model gates. Exact Python 3.11 tests and one-command report execution remain target-environment validation.

`scripts/validate_advanced_04_18.py` is the current strict Python 3.11 correctness handoff; it invokes `scripts/validate_advanced_04_17.py` first. It retains every unresolved predecessor correctness gate before Prompt 16/17 tests and report generation; fixture mechanics never imply service/model compatibility or quality promotion.

- Prompt 18: implemented on `feat/advanced-18-cticonnect-adapter` from Prompt 17 final `1a39055dba7938f96b2462d1392e0f617242597b`; implementation/test head before handoff docs is `545a9efc73c0204f9a07b4c75bec2bf5df9f01d7`. It pins/audits CTIConnect v1.0.0 at `554797d69a51147f1f98fad7198cb2d2b183d0e9`, separates query/official-label boundaries, reproduces official alternate-target identifier scoring, maps target/source-proxy qrels separately, rebuilds BM25 from text, excludes extracted graph assets from truth, and adds `scripts/validate_advanced_04_18.py` chaining P04-P17 before P18 gates. Exact Python 3.11/external-corpus outcomes remain target-environment validation.
