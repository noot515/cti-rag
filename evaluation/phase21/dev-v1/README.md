# Phase 21 evaluation seed corpus

This directory is evaluation-only. `queries.jsonl` contains 270 frozen development/adversarial queries and `judgments.jsonl` contains the separate relevance/answer-key records. No file in this directory is an ingestion source or index input.

Each of the five runtime domains has 50 machine-generated development cases. Those judgments are explicitly `machine_generated_unreviewed`; they are not called gold. The additional 20 cases are `synthetic_contract` fixtures used for failure detection.

Source family, duplicate group, temporal bucket, and split are explicit. Duplicate-group members must remain in one split. Human-reviewed pooled judgments are a separate required gate.

`fixture-runs.json` is mechanics-only. Its provider is `deterministic_fake`; the harness therefore records semantic model metrics as not run. It exists to test reproducibility and B0/B8 accounting, not retrieval quality.

Reproduce the fixture report with:

```bash
python scripts/run_phase21_evaluation.py \
  --config evaluation/phase21/dev-v1/experiment-config.json \
  --queries evaluation/phase21/dev-v1/queries.jsonl \
  --judgments evaluation/phase21/dev-v1/judgments.jsonl \
  --runs evaluation/phase21/dev-v1/fixture-runs.json \
  --report /tmp/phase21-fixture-report.json
```
