# Advanced RAG implementation prompt status

This directory tracks implementation-state handoffs, not the full external prompt pack.

- Prompt 01: predecessor accepted on stacked branch `feat/advanced-01-offline-foundation` at `312e11837bde5b525d277bf7387c57ce30487bb3`.
- Prompt 02/03: implemented and later validated on Windows/Python 3.11, including full repository collection at that stack.
- Prompt 04/05: implemented; focused sandbox gates passed, but their exact later Python 3.11 chain remains tracked separately.
- Prompt 06: implemented on `feat/advanced-06-snapshot-publication`; focused publication/recovery sandbox gate passed (`14 passed`).
- Prompt 07: implemented/documented on `feat/advanced-07-chunk-exact-lexical`; exact full-checkout Python 3.11 chain remains separately unresolved.
- Prompt 08: implemented/documented on `feat/advanced-08-embedding-provider-contract`; focused sandbox gate passed (`12 passed`).
- Prompt 09: implemented/documented on `feat/advanced-09-milvus-projection` at `b76830493d41bb0b6931187ffbd8a406299aedb3`; combined Prompt 08/09 offline gate passed (`24 passed`), while real Milvus service/isolation remained separate.
- Prompt 10: implemented/documented on `feat/advanced-10-neo4j-evidence-projection` at `1667ddb1d155412a46fa86c3c17acef30d76da54`; revision-preserving graph projection, bounded shared traversal, fixture graph publication and isolated Neo4j service tests are present. Focused local mechanics gate passed (`15 passed`); real Neo4j service/isolation remains separate.
- Prompt 11: implemented on `feat/advanced-11-deterministic-query-planner` from Prompt 10 head `1667ddb1d155412a46fa86c3c17acef30d76da54`; deterministic CTI planning, explicit target-object projection, reviewed 2-hop vs explicit 3-hop mapping semantics and a chained Prompt 04-11 validator are present. Focused local planner/target gate passed (`18 passed`), combined Prompt 10/11 mechanics passed (`33 passed`). Exact Python 3.11 chained validation remains `not_run` in the implementation sandbox because Python 3.11 and Docker are unavailable.

`scripts/validate_advanced_04_11.py` is the current correctness handoff. It chains the prior unresolved Prompt 04/05, 06/07 and 08/09 Python 3.11 gates before Prompt 10/11, then compile/whitespace/full-collection checks and available service configuration gates. Skipped prerequisites must remain explicitly reported.