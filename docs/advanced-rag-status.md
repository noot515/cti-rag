# Advanced RAG V3 implementation status

Updated: 2026-09-18. Prompt 17 final predecessor: `1a39055dba7938f96b2462d1392e0f617242597b`. Prompt 18 implementation/test head before handoff documentation: `545a9efc73c0204f9a07b4c75bec2bf5df9f01d7`. Current stacked branch: `feat/advanced-18-cticonnect-adapter`. Legacy retrieval/benchmark behavior remains available and unchanged.

## Prompt 16 - isolated authenticated advanced API

Prompt 16 provides the default-disabled direct `POST /chat/advanced-retrieval` route, lazy legacy-router assembly, a service-inert fixture app factory, strict request validation, grant-before-runtime ordering, separate `evidence:debug` permission, final pre-serialization authorization/finalization, and explicit 401/403/422/503/no-evidence semantics. The direct application URL has no implicit `/api` prefix. Exact Prompt 16 Python 3.11 ASGI/import-safety execution remains part of the chained target-environment gate rather than an inferred pass.

## Prompt 17 - native retrieval, answer and citation evaluation

Prompt 17 adds an evaluation path beside the legacy benchmark without changing the legacy comparator:

- `benchmark/advanced/metrics.py` implements deduplicated target-object Hit/Recall/MRR/nDCG at named k, complete-path alternatives, evidence-document recall only when separate evidence labels exist, citation validity independently from judged support, unanswerable false-evidence/abstention metrics, deterministic seeded cluster bootstrap, and the preregistered noninferiority lower-bound rule;
- all metric results retain explicit status/reason/support/annotation coverage/value. Empty/unjudged labels become `not_applicable`, missing models/judgments remain null `not_run`, and small bootstrap samples become `inconclusive` rather than numeric successes;
- `benchmark/advanced/splits.py` creates deterministic grouped dev/test manifests using both object/report clusters and near-duplicate query families. The manifest records seed plus grouping/split SHA-256 hashes and rejects transitive leakage;
- `benchmark/advanced/ablations.py` preregisters R1 dense, R2 lexical, R3 dense+lexical, R4 +exact, R5 +graph, R6 +single final reranker, and equal-budget C1 basic/structured context. Candidate/final/context budgets remain fixed and authorization cannot be ablated;
- `run_retrieval_eval` executes the deterministic fixture ingestion/indexes without reading qrels/path annotations, freezes the grouped split and per-query channel/ablation predictions first, and only then opens evaluation labels. Exact/lexical/dense/graph evidence still passes the public-fixture policy before it contributes to rankings;
- the fixture command writes `config.snapshot.yaml`, `environment.json`, a corpus manifest snapshot, `split.manifest.json`, `per_query.jsonl`, retrieval/answer/latency metrics, `ablation_summary.csv`, and `report.md`; the configuration snapshot is emitted from the validated secret-free config model rather than raw environment data;
- failed query executions remain present in `per_query.jsonl`; latency records sample count, sequential concurrency and cache state, and explicitly makes no throughput claim;
- the fixture has no configured final reranker, generator, or independent judge. R6, C1 answer/context quality, answer generation, citation support, abstention/false-evidence behavior, and real-quality promotion therefore serialize as null `not_run`, not fallback scores;
- L0 object retrieval remains `not_comparable` unless a canonical legacy object mapping is supplied. Separate evidence-document metrics remain `not_applicable` because the fixture currently provides object qrels but no independent evidence-document labels;
- graph-gain bootstrap is restricted to mapping queries and is distinct from held-out-edge generalization. The synthetic catalog fixture reports mechanics only; held-out-edge/generalization and real-quality promotion remain unrun quality gates;
- optional future generator/judge use requires explicit model-egress permission plus exact model identifiers. Prompt 17 itself ships no default model/judge adapter and performs no external model egress.

### Prompt 17 validation surfaces

Required target commands are:

```text
python -m pytest tests/unit/benchmark tests/e2e/test_eval_report.py -q
python -m benchmark.advanced.run_retrieval_eval --config benchmark/advanced/configs/fixture.yaml --output saves/eval/fixture
python -m benchmark.advanced.run_answer_eval --config benchmark/advanced/configs/fixture.yaml --output saves/eval/fixture-answers
```

Committed tests cover hand-calculated k metrics, duplicate targets, graded nDCG, empty labels, first-hit ordering, complete versus broken paths, citation-validity/support separation, unanswerable metrics, deterministic bootstrap, small-sample inconclusiveness, authorization-preserving/fair ablation budgets, transitive grouped-split leakage, retained failed queries and complete report artifacts.

The exact Prompt 16/17 target commands remain `not_run` in this implementation sandbox: Python is 3.13.5, Python 3.11 is unavailable, Docker is unavailable, and direct GitHub/package-network DNS is unavailable. No target-environment, real-service, model, or quality gate is inferred from code publication.

## Chained validation

`scripts/validate_advanced_04_17.py` is the strict Python 3.11 handoff. It runs the existing Prompt 04-15 chain, Prompt 16 API/import-safety gates, Prompt 17 unit/E2E tests, both offline report commands, compileall, `git diff --check`, full repository collection, status and final HEAD.

## Remaining operational/quality gates

- `python scripts/validate_advanced_04_17.py` on a complete Python 3.11 checkout with pinned advanced dependencies;
- real Milvus and Neo4j roundtrip/legacy-isolation gates inherited from prior phases;
- deployment wiring and operator signing authority for the protected route;
- production restricted-marking policy;
- explicit reranker/generator/judge adapters and their destination authorization;
- real grouped held-out retrieval/answer data large enough for the 2,000-resample cluster-bootstrap gates;
- R6-vs-R5 Recall@10 noninferiority lower 95% bound >= -0.01 and graph mapping-subset gain lower bound > 0 on adequate held-out data.

## Handoff

Prompt 17 mechanics and honest-gate contracts are implemented on top of Prompt 16. No default route or quality promotion is authorized by the synthetic fixture report.

## Prompt 18 - CTIConnect corpus adapter and external retrieval experiment

Prompt 18 adds a benchmark-only adapter for the external `peng-gao-lab/CTIConnect` checkout pinned at `554797d69a51147f1f98fad7198cb2d2b183d0e9`.

- the pinned release is the 1,859-item v1.0.0 dataset (RCM 290, WIM 308, ATD 261, ESD 280, ATA 160, VCA 219, CSC 111, TAP 135, MLA 95); later upstream 1,860-item/VCA-220 state is treated as dataset drift and is not silently accepted;
- `benchmark/cticonnect/adapter.py` verifies the exact Git revision, required MIT/CC-BY-4.0 license declarations, official task counts and SHA-256 values, structured KB file counts/hashes and the 321-report corpus before evaluation;
- the external checkout is referenced only through `CTICONNECT_PATH`; benchmark data are not vendored into this repository;
- structured records parse nested JSON in `contents` and derive identity from `cve_id`, `CWE-` + `cwe_id`, `CAPEC-` + `capec_id` or `mitre_id`. Repeated outer numeric `id` values remain provenance only;
- report records use the supplied `preprocessed`, `link` and `publish_date` fields with exact `BLOG-<id>` mapping. No report URL is fetched;
- query records contain only the question plus non-answer task/category/eval-type metadata. Official answers, target IDs, alternate target IDs, reference answers, construction provenance and source clusters stay in the scoring side;
- official identifier scoring is compatibility-pinned to the upstream behavior, including the all-valid alternate-target shortcut and the mixed valid/invalid fallback to canonical-gold P/R/F1;
- target-object qrels and source-document proxy qrels are separate. Source proxies are explicitly nonexhaustive and are never represented as evidence/path truth;
- `cskg/` lineage is recorded separately as extracted. The graph is not converted into ground-truth edges and `cskg/bm25_index.pkl` is never unpickled; the retrieval experiment rebuilds BM25 from corpus text;
- the generic advanced retrieval runner lazily dispatches to CTIConnect only for corpus ID `cticonnect-v1.0.0`, preserving the Prompt 17 fixture path unchanged;
- real embedding/reranker/generator/judge variants remain `not_run` unless an exact permitted model configuration exists; lexical external retrieval alone does not authorize quality promotion.

### Prompt 18 validation

Target commands:

```text
python -m pytest tests/unit/benchmark/test_cticonnect_adapter.py -q
python -m pytest tests/integration/test_cticonnect_corpus.py -m integration -q
python -m benchmark.advanced.run_retrieval_eval --config benchmark/advanced/configs/cticonnect.yaml --output saves/eval/cticonnect
python scripts/validate_advanced_04_18.py
```

The chained validator first executes `scripts/validate_advanced_04_17.py`, then Prompt 18 unit tests, the pinned-corpus integration and external retrieval report when `CTICONNECT_PATH` is present, followed by compileall, `git diff --check`, full collection, status and HEAD. Missing `CTICONNECT_PATH` is reported as an explicit optional `NOT_RUN`, not a pass.

The exact Python 3.11 chain and external-checkout commands remain target-environment gates in this implementation environment; no new pass count is inferred from publication.

## Prompt 18 handoff

Prompt 19 may build from this branch only after treating the unresolved P04-P18 Python 3.11 chain as a correctness prerequisite. CTIConnect remains an evaluation dependency, not an application runtime dependency.
