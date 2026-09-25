# Phase 21 implementation report — rigorous multidomain retrieval and grounding evaluation

Status: **deterministic evaluation gates passed; real-model/GPU/human-review gates remain blocked; cumulative acceptance remains blocked**

## Lineage and executed validation

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/20-report.md`
- Validated code checkpoint: `7ce8fe6f3a6d5948725eea9750e035a68069770f`
- Actions run/job: `36117845446 / 108016031013`
- Python: **3.13.15**
- Cumulative deterministic suite through Phase 22: **192/192 passed in 58.587 s**
- Phase 21 invariant gate: **9/9 passed in 44.702 s**
- Frozen Phase 21 report gate: **passed**
- Frozen report digest: `0792ec472861f1e8a9ad343c0ffa6e351b46c198f6eaee0236dfe24a25a5d14e`
- Frozen report hard-gate failures: **none**
- Frozen report budget failures: **none**
- Affected legacy API regressions: **8/8 passed**
- Cumulative registry through Phase 22: executed successfully and intentionally remains overall fail-closed because required external/prerequisite gates are blocked.

## Versioned evaluation data

`evaluation/phase21/dev-v1/` now contains separate, frozen artifacts:

- `corpus.jsonl`: **779** indexable evaluation records.
- `queries.jsonl`: **280** queries.
- `judgments.jsonl`: **280** separate judgment records.
- `splits.json`: source-family, duplicate-group, temporal, and adversarial partitions.
- `manifest.json`: version/count/index-exclusion contract.
- `experiment-config.json`: seed, baselines, bootstrap settings, noninferiority margins, latency/resource budgets.
- `fixture-runs.json`: deterministic mechanics-only B0–B8 outcomes.

Query coverage is 50 development queries for each of cybersecurity, networking, quant, humanities, and privacy, plus 10 cross-domain development queries and 20 adversarial contract cases. Judgments comprise **260 machine-generated/unreviewed** records and **20 synthetic contract** records; **0 are labeled human reviewed**.

Only `corpus.jsonl` is listed as an evaluation index input. Query text, judgments, answer keys, split assignments, run outputs, and configs are excluded. Indexable corpus text contains no relevance grade or query identifier wording.

## Metrics and experiment design

The harness measures:

- candidate recall@20/50/100, MRR, nDCG@10;
- relevant-source recall, router recall, and ANN recall;
- subquestion and graph-edge coverage;
- exact structured-value correctness;
- packing survival;
- citation-support precision/recall;
- answerable coverage, false abstention, and error among answered queries;
- p50/p95 total and stage latency, RAM and optional VRAM;
- backend, policy, and temporal failure counts;
- duplicate-origin excess.

B0–B8 are explicit. Frozen mechanics runs use identical scope, snapshot, candidate budget, and resource condition. Feature-level ablations include B1→B3, B2→B3, B3→B4, B4→B5/B6/B7, and B7→B8 so cumulative changes are not automatically attributed to every feature.

Paired query-level bootstrap intervals are deterministic from the predeclared seed. Noninferiority margins are 0.01 absolute for nDCG@10 and Recall@50. Underpowered slices remain explicitly inconclusive; per-domain and per-task slice regressions/inconclusive slices are emitted.

## Failure gates

Dedicated fixtures verify that the metrics independently detect:

- seeded bad routing;
- future-revision leakage;
- duplicate-source boosting;
- wrong structured/numerical output;
- unsupported citations.

The frozen B0–B8 fixture report is required to have zero hard-gate failures and stay within declared resource budgets before its gate exits successfully.

## Model and diagnostic honesty

All committed B0–B8 fixture runs use `model_execution=deterministic_fake` with provider fingerprint `fixture-ranking/1`. Their semantic-model metric status is `not_run_fake_or_no_model`; no fake provider is promoted as real embedding, reranking, or generation quality.

The optional RAGChecker adapter imports no external SDK into core evaluation and requires both reviewed data-exposure authorization and a real-model execution classification before producing external model-judged diagnostics.

## Reproducibility fingerprints

The report digest binds SHA-256 fingerprints of the frozen config, corpus, queries, judgments, and run file before the report digest is computed.

Repository blob fingerprints at the validated checkpoint include:

- evaluation harness: `1e60bd7960c4a632ff729d45e2cb88f865ea6a47`
- metrics: `cd7d2cac8eb2008f92841ca2a6b4ea871efdbf2f`
- external diagnostic adapter: `51c8d7ed0e40332674809ed156ae1ff95c71dc2c`
- corpus: `3e8d22b264b3a64847f109ccfc156a512a08232e`
- queries: `416535130aa08df4b11a9ac86ead8a403c67e1b4`
- judgments: `7ae5434cfb2eb381c47510f6196a6bb75bf5cb4d`
- deterministic B0–B8 runs: `241dff5537d8315cfcf5f83ae88305981a46b698`
- experiment config: `13945c7895986c144394aca442df78f242c79015`
- split manifest: `1c1e807f165cff1a0ba60df6424eb453391fe816`

## Blocked required evidence

The following Phase 21 gates remain blocked and are **not** counted as passes:

- `phase21-real-embedding-quality`
- `phase21-real-reranker-quality`
- `phase21-real-generator-grounding-quality`
- `phase21-gpu-concurrent-resource-profile`
- `phase21-human-reviewed-judgments`

No approved pinned real model/GPU runtime or human-reviewed pooled judgments were available in CI.

## Migration and rollback

Phase 21 is additive evaluation infrastructure. It does not alter serving indexes, policy state, evidence revisions, or snapshot publication. Removing `cti_rag/evaluation` and the versioned evaluation directory returns to the previous runtime behavior without data migration.

## Handoff

Phase 22 is implemented and validated independently. Cumulative promotion remains blocked by Phase 14 and the inherited/live required gates.
