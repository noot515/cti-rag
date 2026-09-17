# Current state and sequencing handoff

Prompt 17 begins from Prompt 16 documented head `1b0e03fc3a54367cb0930318db6477a2667b8e02` on `feat/advanced-16-authenticated-advanced-api` and is stacked on `feat/advanced-17-native-evaluation-and-ablations`. Prompt 17 implementation/test head before final documentation is `9fd83dc85c4575f3ef6518940449a0d93af494e5`.

Reconciliation notes:

1. Prompt 16 remains the authenticated native HTTP boundary. Prompt 17 evaluates native advanced retrieval mechanics beside the legacy benchmark and does not change route defaults or legacy algorithms.
2. Retrieval execution is label-blind: fixture query records are checked for answer/qrel fields, the grouped split is frozen, and exact/lexical/dense/graph predictions are frozen before object qrels or path annotations are opened.
3. Exact/lexical/dense/graph fixture results still pass the public-fixture authorization policy. There is no authorization ablation in the evaluation matrix.
4. Target-object ranking is deduplicated before Hit/Recall/MRR/nDCG. Complete-path scoring requires an entire acceptable ordered-object alternative; a prefix/broken path is not partial credit.
5. Evidence-document metrics require their own labels. Existing fixture object qrels are not silently reused as document labels.
6. Citation validity and independently judged claim support are different metrics. Citation validity never creates a support score when a judge annotation is missing.
7. Unanswerable false-evidence and abstention rates are separate contracts. The current offline answer runner reports them `not_run` because no answer generator is configured.
8. The grouped split uses both object/report cluster and near-duplicate query family, including transitive unions, before producing deterministic seed/grouping/split hashes. No held-out labels are used to form groups.
9. R1-R6 and C1 are preregistered with fixed top-k, pre-rerank and context budgets. R1=dense, R2=lexical, R3=dense+lexical, R4=+exact, R5=+graph, R6=+single final reranker; C1 compares basic/structured formatting under equal budgets.
10. The fixture config has deterministic local embedding but no final reranker/generator/judge. R6, C1 answer/context quality and answer/judge metrics therefore remain null `not_run`; no fallback ranking is mislabeled as reranker quality.
11. L0 object retrieval remains `not_comparable` without a canonical legacy object mapping. The legacy comparator itself is not modified to improve scores.
12. The one-command retrieval report writes validated/secret-free config, environment, corpus and frozen split snapshots, per-query records, retrieval/answer/latency metrics, ablation CSV and Markdown. Failed queries/timeouts remain in per-query output; latency states sample count/concurrency/cache state and no throughput claim.
13. Paired cluster bootstrap is fixed at 2,000 resamples by default. A lower 95% bound >= -0.01 is the noninferiority criterion. Graph gain is computed only on the mapping subset and requires lower bound > 0. Missing/small independent clusters are `inconclusive`.
14. Catalog mapping on the synthetic fixture is not a held-out-edge generalization experiment. Held-out-edge and real-quality promotion gates remain separately `not_run` until adequate grouped held-out data exists.
15. Optional future generator/judge egress requires explicit permission plus exact model identifiers. This phase ships no default model/judge adapter, so the required offline answer command remains network-free and reports unavailable metrics honestly.
16. `scripts/validate_advanced_04_17.py` is the strict target handoff: predecessor P04-15 chain -> P16 API/import safety -> P17 metrics/report tests -> both fixture report commands -> compile/diff/full collection/status/HEAD.
17. Prompt 16's advanced fixture app remains an injected-runtime application boundary; Prompt 17 directly exercises the concrete local exact/lexical/dense/catalog-graph fixture indexes. The Prompt 16 ASGI exit gate must still demonstrate the final injected runtime wiring before deployment promotion.
18. The implementation sandbox still has Python 3.13.5, no Python 3.11, no Docker and no direct GitHub/package DNS. Exact target tests/report commands remain `not_run` here rather than inferred from implementation.
