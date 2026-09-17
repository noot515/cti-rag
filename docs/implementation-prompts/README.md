# Advanced RAG implementation prompt status

This directory tracks implementation-state handoffs, not the full external prompt pack.

- Prompt 01: predecessor accepted on stacked branch `feat/advanced-01-offline-foundation` at `312e11837bde5b525d277bf7387c57ce30487bb3`.
- Prompt 02: implemented on `feat/advanced-03-generic-evidence-contracts`; baseline/evaluation-boundary correctness gate passed and was later validated on Windows/Python 3.11.
- Prompt 03: implemented on the same stacked branch; generic identity/provenance/policy/channel correctness gate passed and was later validated on Windows/Python 3.11.
- Prompt 04: implemented/documented on `feat/advanced-04-cti-domain-adapter`; focused sandbox gate passed (`28 passed`). Exact later Python 3.11 chain remains tracked separately.
- Prompt 05: implemented on `feat/advanced-05-durable-evidence-catalog`; focused sandbox gate passed (`12 passed`) and combined Prompt 04/05 sandbox gate passed (`40 passed`). Exact later Python 3.11 chain remains tracked separately.
- Prompt 06: implemented on `feat/advanced-06-snapshot-publication` at `fb9a816ac083741fcce245c4e0b02fbd001e7c6e`; focused publication/recovery sandbox gate passed (`14 passed`).
- Prompt 07: implemented/documented on `feat/advanced-07-chunk-exact-lexical` at `ecc28482f57e93fa6d90cbf99f90146c762cd9fb`; exact full-checkout Python 3.11 chain remains separately unresolved.
- Prompt 08: implemented/documented on `feat/advanced-08-embedding-provider-contract` at `397f3ba49b94bc93a462b7e09c2f7d51f76bd4c5`; focused sandbox gate passed (`12 passed`).
- Prompt 09: implemented/documented on `feat/advanced-09-milvus-projection` at `b76830493d41bb0b6931187ffbd8a406299aedb3`; combined Prompt 08/09 fake/offline gate passed (`24 passed`); real Milvus service/isolation and exact Python 3.11 chain remain separate.
- Prompt 10: implemented on `feat/advanced-10-neo4j-evidence-projection` from Prompt 09 head `b76830493d41bb0b6931187ffbd8a406299aedb3`; revision-preserving catalog/Neo4j graph projection, bounded shared traversal, fixture graph publication, isolated Neo4j service profile and real-service integration tests are present. Focused local mechanics gate passed (`15 passed`); real Neo4j service/isolation and exact Python 3.11 chain remain `not_run` in the implementation sandbox.
- Prompt 11+: not implemented on this branch.

Skipped prerequisites and release blockers are recorded in `docs/advanced-rag-status.md` and `docs/advanced-service-matrix.md`. A fake/in-memory gate must not be reported as real-service compatibility.