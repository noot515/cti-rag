# Advanced RAG V3 implementation status

Updated: 2026-09-16. Reviewed application baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`. Implemented scope: supplied V3 **P00 and P01 only**. The advanced path remains disabled by default; legacy retrieval remains available.

## P00 — offline import/config/test foundation

Implemented:

- `packages` no longer constructs `Config`, a `ThreadPoolExecutor`, Milvus/Neo4j wrappers, knowledge base, graph base, or retriever during a plain package import.
- Legacy public access remains lazy through explicit getters and compatibility attributes. `packages.config` remains usable after Python replaces the package-level lazy proxy with the imported submodule.
- `packages.core` exports existing core/database symbols lazily rather than importing both backend stacks on `import packages.core`.
- `packages.evidence.config.AdvancedRagConfig` is strict, frozen, default-disabled and profile-aware. The fixture profile rejects network/download/web/remote-provider configuration after all override layers are merged; a `TAVILY_API_KEY` cannot turn advanced fixture web access on.
- Initial V3 limits are represented in config: dense/lexical/graph candidate limits 40, graph general/mapping hops 2/3, eight seeds, 30 neighbors, 40 paths, 1,000 visited nodes, 10/3/4-second request/channel/reranker deadlines, context cap 8,000 tokens and 15 evidence blocks.
- Advanced requirements are isolated and exactly pinned. The installed package metadata supports Python 3.11, although this sandbox only provides Python 3.13.5.
- pytest recognizes both `test_*.py` and `*_test.py`. The syntactically incomplete/import-time HTTP `test_ner.py`, live Milvus script `test_milvus_fix.py`, and module-stubbing Redis `model_router_test.py` are isolated from default offline collection. Service/live markers are excluded by default.

Validation evidence: `evaluation/advanced/p00-offline-foundation.json`.

## P01 — generic evidence/CTI contracts and policy boundary

Implemented generic contracts under `packages/evidence/`:

- versioned canonical SHA-256 identities for objects, revisions, relations/assertions, chunks and paths;
- domain in object identity, so equal source IDs or normalized names across domains cannot merge implicitly;
- deterministic canonical JSON with explicit UTC normalization and finite/JSON-safe validation;
- typed `SourceRef`, `ExternalIdentifier`, `EvidenceObject`, `EvidenceRelation`, `EvidenceChunk`, `EvidencePath`, retrieval request/candidate/result, citation and policy-view contracts;
- independently identifiable relation assertions so two source records with identical endpoints do not collapse;
- fail-closed `DenyByDefaultPolicy` and an explicitly scoped `PublicFixturePolicy`; destination authorization is separate from domain normalization.

Implemented CTI semantics under `packages/domains/cti/`:

- minimal `DomainAdapter` boundary with direct `CtiDomainAdapter`; no registry or second-domain skeleton;
- typed `CtiObject`, `CtiRelationship`, `CtiChunk` and CTI family data for vulnerabilities, weaknesses, attack patterns/techniques, reports and other source types;
- whole CVE/CWE/CAPEC/ATT&CK identifier parsing and exact keys without alias/name guessing;
- TLP 2.0 labels including AMBER+STRICT without a numeric clearance hierarchy;
- marking definitions, refs and granular selectors preserved as policy-relevant metadata; missing/unknown definitions are unresolved and therefore fail closed under the fixture policy;
- reviewed, bounded relation patterns only; no generated Cypher or arbitrary relation traversal;
- `report.object_refs` become explicit `references` assertions with source-field locators, not causal edges;
- deterministic synthetic fixture with `CVE-2026-999999 -> CWE-79 -> CAPEC-66 -> T1059.001`, `T9999` distractor, and two independently sourced CWE→CAPEC assertions to test multiplicity.

Validation evidence: `evaluation/advanced/p01-evidence-contracts.json`.

## Validation results and limits

| Gate | Result |
|---|---|
| P00 focused import/config suite | **16 passed** |
| Combined P00/P01 pure unit suite | **41 passed** |
| Generic/CTI JSON round trips | **passed** |
| Domain-separated revision identity | **passed** |
| Same-endpoint relationship multiplicity | **passed** |
| Cross-domain name/source-ID non-merge | **passed** |
| Deny/default, destination and marking failure cases | **passed** |
| Fresh-process no-network/no-write import behavior | **passed** |
| Legacy lazy Config compatibility smoke | **passed** |
| `compileall` for changed Python modules | **passed** |
| Exact Python 3.11 test run | **not_run** — interpreter unavailable in sandbox |
| Full checkout `pytest --collect-only` | **not_run** — sandbox cannot clone the complete repository |
| Milvus/Neo4j/OpenCTI/model/quality tests | **not_run** — outside P00/P01 |

P02 has **not** been implemented. There is no durable SQLite catalog, raw-payload store, snapshot publication protocol, Milvus/Neo4j advanced projection, retrieval orchestrator, advanced API, OpenCTI sync or quality claim in this change.
