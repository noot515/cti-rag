# Advanced RAG implementation prompt status

This directory tracks implementation-state handoffs, not the full external prompt pack.

- Prompt 01: predecessor accepted on stacked branch `feat/advanced-01-offline-foundation` at `312e11837bde5b525d277bf7387c57ce30487bb3`.
- Prompt 02: implemented on `feat/advanced-03-generic-evidence-contracts`; baseline/evaluation-boundary correctness gate passed and was later validated on Windows/Python 3.11.
- Prompt 03: implemented on the same stacked branch; generic identity/provenance/policy/channel correctness gate passed and was later validated on Windows/Python 3.11.
- Prompt 04: implemented/documented on `feat/advanced-04-cti-domain-adapter` at `19f7e6fe86fd6e3eb5b61cb6ece9d44143482bac`; focused sandbox gate passed (`28 passed`).
- Prompt 05: implemented on `feat/advanced-05-durable-evidence-catalog`; focused durable-store sandbox gate passed (`12 passed`) and combined Prompt 04/05 sandbox gate passed (`40 passed`).
- Prompt 06: implemented on `feat/advanced-06-snapshot-publication` at `fb9a816ac083741fcce245c4e0b02fbd001e7c6e`; focused publication/recovery sandbox gate passed (`14 passed`).
- Prompt 07: implemented/documented on `feat/advanced-07-chunk-exact-lexical` at `ecc28482f57e93fa6d90cbf99f90146c762cd9fb`; deterministic chunks, persistent exact/full-corpus lexical projections and chained validation entry point are present. Exact full-checkout Python 3.11 gate remains separately `not_run` in the implementation sandbox.
- Prompt 08: implemented on `feat/advanced-08-embedding-provider-contract` from Prompt 07 head `ecc28482f57e93fa6d90cbf99f90146c762cd9fb`; implementation code reached `14df9ae472fa0bb54e6e574ec02d100b05bb9d63` before documentation. Fingerprint-bound provider contracts, deterministic fixture embeddings, generation-scoped dense projection/channel, egress checks and optional model dependencies are present. Focused sandbox gate passed (`12 passed`).
- Prompt 09+: not implemented on this branch.

Exact Python 3.11/full-repository gates where not already separately verified, optional real-model/service compatibility and quality gates are tracked in `docs/advanced-rag-status.md` and must not be inferred from local fixture tests.
