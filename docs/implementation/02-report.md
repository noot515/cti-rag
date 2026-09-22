# Phase 02 implementation report — ports, domain registry, and foundational authorization

Status: **implementation gate passed; cumulative acceptance remains blocked by inherited Phase 0 runtime gates**

## Checkpoint and lineage

- Repository: `noot515/cti-rag`
- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/01-report.md`
- Phase 02/03 code checkpoint: `78ed1e532fd7be9d9c28ce3e10ad5a13afdcf9e3`
- Config fingerprint: `config.yaml` blob `a90848b9f9884c344d3fe2cc10cd6ec8c13da591`
- Baseline benchmark corpus fingerprint: `benchmark/dataset.xlsx` blob `5820fa64bed3db3147d52d632975a21101893bff`
- Baseline model material fingerprint: `models/neo4j_final_agent.pt` blob `b06a0a7f5e5209553993045009c4e878b54a6435`
- No real model was invoked in this phase.

## Implemented

Small backend-neutral ports now exist for source connectors, normalizers, evidence storage, exact/lexical/dense search, graph traversal, structured execution, snapshots, models, and policy. Capability descriptors declare mandatory filter support, temporal modes, snapshot support, model fingerprints, languages, cancellation, pagination, batch limits, and score direction. Channel results distinguish `ok`, `empty`, `timeout`, `unavailable`, `unsupported`, and `rejected`.

Five pure domain specifications are registered for cybersecurity, networking, quant, privacy, and humanities. Each declares schemas, identifier parsers, query templates, relation rules, and deterministic fixtures. A sixth domain can be registered dynamically without editing orchestration or fusion.

The local policy provider derives immutable execution scope from an authenticated principal plus server-owned policy. Client payloads whitelist only narrowing fields. Public-only local mode permits only public evidence and local model destinations; private scope requires a working policy rule with explicit private-state authorization.

Model dispatch authorization covers embedding, translation, extraction, reranking, and generation. Search helpers authorize and validate required backend capabilities before calling a backend. Optional SDKs remain outside the minimal import graph and the RuntimePolicy adapter remains deferred.

## Validation actually executed

```text
python -m compileall -q cti_rag scripts tests
python -m unittest tests.contracts_phase1_test tests.validation_runner_test tests.ports_policy_phase2_test tests.canonical_ingestion_phase3_test -v
```

Result for the cumulative deterministic suite: **34/34 passed**, including **8 Phase 02 policy/port/domain tests**.

Measured execution environment: Python 3.13.5, Linux 6.18.44 x86_64; 5.07 s wall time and 98,480 KB maximum resident set size for the 34-test suite.

Acceptance fixtures passed:
- minimal contract/port/domain/policy/composition import graph has no Milvus/Neo4j/OpenCTI/SQLAlchemy/FastAPI/model SDK import;
- a sixth domain registers without orchestrator changes;
- forged client principal/tenant/clearance fields cannot grant access;
- denied/policy-failed requests make zero backend calls;
- missing mandatory backend filters reject before search;
- local-only evidence cannot be sent to a remote reranker.

## Limitations and rollback

The real external RuntimePolicy adapter is intentionally not implemented here. Search/database/model adapters are still injected fakes or future concrete backends, and the new retrieval path remains disabled in the legacy API.

Rollback is a revert of the additive Phase 02/03 commits. No legacy API route, database credential, service port, live index, or user data was changed.
