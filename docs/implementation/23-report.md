# Phase 23 implementation report — measured optimization against frozen quality/resource gates

Status: **deterministic optimization mechanics passed; production optimization remains blocked pending comparable real-runtime measurements**

## Lineage and validation

- Parent implementation report: `docs/implementation/22-report.md`
- Parent documented head: `760197338e46c9c4d03e7da086ed2bf539c68515`
- Validated Phase 23/24 code checkpoint: `4a62bc06d64204ccfb72c9fcd55d7b086cb799a3`
- Actions run/job: `36134108297 / 108067939377`
- Python: **3.13.15**
- Cumulative deterministic suite through Phase 24: **203/203 passed in 31.308 s**
- Phase 23 invariant gate: **6/6 passed in 0.041 s**
- Affected legacy API regressions: **8/8 passed**
- Cumulative validation registry through Phase 24: **verified successfully while intentionally fail-closed**

## Bottleneck measured before algorithm changes

The existing planner already skips semantic/text planning for exact identifier fast paths, executes independent DAG work concurrently, bounds reranking, and uses bounded caches/queues. The first concrete optimization target was therefore canonical hydration.

`evaluation/phase23/bottleneck-profile.json` records an executed 40-candidate deterministic backend-operation profile:

- prior point hydration: 40 canonical evidence reads + 40 metadata reads = **80 backend read operations**
- optional bulk hydration with batch size 16: 3 canonical evidence reads + 3 metadata reads = **6 backend read operations**
- canonical revision/provenance/text/snapshot/policy validation is unchanged
- this measurement is an operation-count profile, **not** a real database/model latency or throughput benchmark

`EvidenceHydrator` now has an opt-in bounded bulk path using provider `get_passages` / `get_many` capabilities when available. Point lookup remains the default and rollback/compatibility path.

## Frozen tuning experiment

The frozen Phase 21 corpus/judgments remain the quality basis. Phase 23 adds:

- `evaluation/phase23/optimization-grid.json`
- `evaluation/phase23/fixture-observations.json`
- `evaluation/phase23/bottleneck-profile.json`
- `config/retrieval-optimization-selected.json`

The tuning partition contains **130** `dev_source_family` queries. The one-shot holdout partition contains **150** duplicate/time/cross-domain/adversarial queries and is disjoint from tuning by declared split name.

The controlled grid varies all requested axes:

- passage size and overlap
- deterministic context-prefix mode
- language analyzer
- lexical candidate window
- dense candidate window
- ANN probe parameter
- reranker candidate count
- context token budget
- graph expansion cap, including text-only
- routing fallback count
- bulk hydration/batch size

Hard identifier/structured obligations, policy scope, snapshot, current revocations, and numerical verification remain fixed controls.

## Selection and rejection behavior

The deterministic fixture selector chose `bulk-hydration-32` on tuning because it preserves fixture quality/hard gates while reducing modeled backend reads. The selected tuning candidate was then evaluated once on the declared holdout together with the baseline.

The harness also rejects plausible but harmful alternatives:

- `lexical-window-20`: Recall@50 noninferiority failure
- `ann-probe-8`: ANN recall noninferiority failure against exhaustive eligible search
- `text-only`: graph-required edge recall failure
- additional prefix/analyzer/rerank/fallback candidates fail critical-slice or quality constraints as configured

Per-domain and per-task fixture slice evidence is recorded for baseline and the chosen candidate, including paired deterministic equivalence intervals. Those intervals establish test mechanics only; they do not substitute for real retrieval/model measurements.

## Production decision

**Production remains `baseline-v1`.**

The Phase 23 report returns:

- tuning choice: `bulk-hydration-32`
- production choice: `baseline-v1`
- status: `blocked`
- performance claim allowed: **false**

The candidate is not promoted because the only Phase 23 observations are `deterministic_fixture`. No approved comparable real backend/model runtime was available for p50/p95 latency, memory, index cost, ingestion cost, ANN behavior, or end-to-end throughput under representative load.

This satisfies the fail-closed rule: an apparently beneficial optimization is implemented behind an opt-in path, but the production configuration and rollback configuration remain unchanged until real-runtime holdout evidence exists.

## Cost/tradeoff accounting

Each configuration records index bytes, ingestion-cost units, backend read operations, operational dependencies, and semantic-risk notes. ANN candidates are compared to exhaustive eligible search and graph-cap/text-only candidates are checked against required-edge recall.

No model-generated prefixes, learned sparse/late-interaction retriever, separate lexical service, or learned router was added because the deterministic evidence did not justify introducing those dependencies.

## Fingerprints

Validated repository blob fingerprints:

- hydration implementation: `f23144fc2eda9e1bd62039e22f65e84a8738a941`
- optimization models: `d81a1fe1c67fe1c4730f4c654642ead2ef74f01d`
- optimization selector: `2210890c2250689a19f161a5d91293064f6c46fa`
- optimization IO: `afe3d4a016d9d92c97f2d336b2abb0c1a2cace03`
- grid: `8d1e6382b89f3954ed4d092bf1f8e13b774a91ce`
- observations: `eaeea0dc2280c1fd97ca7c4dccdebdc0082d4e93`
- bottleneck profile: `7107a643b2b04dc895b9e67f1051c5fce46b1e61`
- selected production config: `bccf68ed5325445160100b30ee84f8219e3ab1af`
- Phase 23 tests: `5afad0e2c1680b7d0da3969ca1222da5f651ffaa`

Corpus/evaluation basis remains Phase 21 `phase21-dev-v1`, with frozen report digest `0792ec472861f1e8a9ad343c0ffa6e351b46c198f6eaee0236dfe24a25a5d14e`. No real model fingerprint is claimed.

## Acceptance status

Passed:

- actual bottleneck profiled before optimization
- exact fast path remains planner-minimal
- optional bulk hydration preserves canonical/policy validation
- every requested sweep axis is varied
- tuning/holdout partitions are explicit and disjoint
- ANN/exhaustive and graph/text-only quality gates are represented
- poor candidate settings are rejected rather than automatically retained
- selected configuration is versioned with explicit rollback configuration
- deterministic per-domain/task slice and paired-interval mechanics are reported

Blocked:

- comparable real-runtime before/after p50/p95 latency
- real RAM/VRAM/index/ingestion measurements under representative load
- production promotion of `bulk-hydration-32`
- any performance/speedup claim

## Rollback

Bulk hydration is opt-in. `baseline-v1` remains both production and rollback selection in `config/retrieval-optimization-selected.json`. Disabling the bulk capability restores the existing point-read path without changing evidence identities, indexes, snapshots, or policy state.
