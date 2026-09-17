# Advanced RAG implementation prompt status

This directory tracks implementation-state handoffs, not the full external prompt pack.

- Prompt 01: predecessor accepted on stacked branch `feat/advanced-01-offline-foundation` at `312e11837bde5b525d277bf7387c57ce30487bb3`.
- Prompt 02: implemented on `feat/advanced-03-generic-evidence-contracts`; baseline/evaluation-boundary correctness gate passed and was later validated on Windows/Python 3.11.
- Prompt 03: implemented on the same stacked branch; generic identity/provenance/policy/channel correctness gate passed and was later validated on Windows/Python 3.11.
- Prompt 04: implemented and documented on `feat/advanced-04-cti-domain-adapter` at `19f7e6fe86fd6e3eb5b61cb6ece9d44143482bac`; focused sandbox gate passed (`28 passed`).
- Prompt 05: implemented on `feat/advanced-05-durable-evidence-catalog`; focused durable-store sandbox gate passed (`12 passed`) and the combined Prompt 04/05 sandbox gate passed (`40 passed`).
- Prompt 06: implemented on `feat/advanced-06-snapshot-publication` at documented head `fb9a816ac083741fcce245c4e0b02fbd001e7c6e`; focused publication/recovery sandbox gate passed (`14 passed`). Publication validation is fake-backend mechanics only, not a real-service atomicity claim.
- Prompt 07: implemented on `feat/advanced-07-chunk-exact-lexical` from Prompt 06 head `fb9a816ac083741fcce245c4e0b02fbd001e7c6e`; implementation/hardening reached `d59673c2fea84373d46b706a6786ea39d9bbe778` before documentation. Deterministic chunks, independent persistent exact lookup, full-generation BM25, exact/lexical publication writers, fixture ingestion CLI, e2e tests and a chained Python 3.11 validator are present. The local Prompt 07 compatibility harness passed, but the exact full-checkout Python 3.11 chained correctness gate remains `not_run` in the current sandbox.
- Prompt 08+: not implemented on this branch.

Exact Prompt 04-07 Python 3.11/full-repository collection where not already separately verified, real-service compatibility and quality gates are tracked in `docs/advanced-rag-status.md`. Do not infer a skipped gate from predecessor or partial-workspace results.
