# Advanced RAG V3 implementation status

Updated: 2026-09-17. Prompt 16 documented head / Prompt 17 predecessor: `1b0e03fc3a54367cb0930318db6477a2667b8e02`. Prompt 17 implementation/test head before final handoff documentation: `9fd83dc85c4575f3ef6518940449a0d93af494e5`. Current stacked branch: `feat/advanced-17-native-evaluation-and-ablations`. Legacy retrieval/benchmark behavior remains available and unchanged.

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
