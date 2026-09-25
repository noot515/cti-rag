# Phase 21 evaluation seed corpus

This directory is evaluation-only. `corpus.jsonl` is the versioned indexable evaluation corpus; `queries.jsonl` contains 280 frozen development/cross-domain/adversarial queries; `judgments.jsonl` contains separate relevance/answer-key records and is never an index input. `splits.json` records independent source-family, duplicate-group, and temporal partitions.

Each of the five runtime domains has 50 machine-generated development cases. Those judgments are explicitly `machine_generated_unreviewed`; they are not called gold. Ten additional cases form a cross-domain development slice. The 20 adversarial cases are `synthetic_contract` fixtures used for failure detection.

Source family, duplicate group, temporal bucket, and split are explicit. `splits.json` keeps source-family assignments, duplicate groups, and historical/current time partitions independently inspectable; duplicate-group members are atomic within their partition. Human-reviewed pooled judgments are a separate required gate.

`fixture-runs.json` is mechanics-only and contains B0 through B8 under identical scope/snapshot/candidate/resource conditions. Its provider is `deterministic_fake`; semantic model metrics remain `not_run_fake_or_no_model`. The runs exercise baseline and feature-level ablation accounting, not real retrieval quality.

Reproduce the fixture report with:

```bash
python scripts/run_phase21_evaluation.py \
  --config evaluation/phase21/dev-v1/experiment-config.json \
  --corpus evaluation/phase21/dev-v1/corpus.jsonl \
  --queries evaluation/phase21/dev-v1/queries.jsonl \
  --judgments evaluation/phase21/dev-v1/judgments.jsonl \
  --runs evaluation/phase21/dev-v1/fixture-runs.json \
  --report /tmp/phase21-fixture-report.json
```
