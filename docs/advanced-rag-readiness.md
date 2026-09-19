# Advanced RAG Prompt 22 release readiness

Updated: 2026-09-19

Branch: feat/advanced-22-release-readiness

Prompt 21 predecessor handoff: 5a9d1e6807bf9261c3d42e088234061e3b046c91

## Decision

The release decision is HOLD. Advanced retrieval remains opt-in. Prompt 22 may produce
"ready_for_explicit_promotion" only when every gate required by the applicable
milestone is recorded as pass; that state still does not perform deployment,
promotion, or a legacy-default switch.

The checked-in matched-corpus profile is deliberately hold-by-default. It contains no
pre-authorized service, security, policy, quality, or deployment pass.

## I1 matched-corpus contract

I1 compares the same recorded OpenCTI capture in two paths:

1. C1-direct: normalize and chunk the recorded source directly.
2. I1-opencti: ingest the same capture through the OpenCTI sync/publication path and
   query the published generation.

Object and relation equivalence is provenance-bearing. The mapping key is kind +
source_object_id + raw_sha256. Local UIDs, local scope IDs, and source_instance may
differ between transports and are recorded separately; names are never identity keys.
Semantic fields, relation direction/assertion kind, evidence payload semantics, and
marking policy must still match. Any matched-content mismatch sets
platform_attribution_permitted=false and blocks readiness.

The deterministic matched fixture compares exact and lexical mechanics only. ANN,
embedding, reranking, generation, real-service compatibility, and judged quality remain
separate gates and are never inferred from the fixture.

## Evidence matrix

| Gate | Current status | Required evidence before pass |
| --- | --- | --- |
| matched content parity | not_run | Prompt 22 comparison command and equivalence-map artifact |
| retrieval parity/tolerances | not_run | Prompt 22 comparison report under fixed query/budget settings |
| rollback mechanics | not_run | focused retained-generation rollback test, including live tombstone overlay |
| predecessor correctness | not_run | Python 3.11 Prompt 04-21 chained validator |
| authorization policy | not_run | policy/isolation unit and E2E gates with no fixture bypass |
| publication recovery | not_run | verified publication/recovery tests for retained and failed generations |
| real OpenCTI | not_run | version-pinned read-only live integration |
| real Milvus | not_run | isolated real-server roundtrip under pinned versions |
| real Neo4j | not_run | isolated real-server roundtrip under pinned versions |
| backend isolation | not_run | legacy-credential and legacy-endpoint isolation probes |
| secret handling | not_run | release review showing no secret/config leakage in artifacts |
| freshness/lifecycle | not_run | reconciliation, lease, withdrawal, and revocation E2E gates |
| judged quality | not_run | comparable grouped held-out judgments |
| R6 vs R5 Recall@10 noninferiority | not_run | 2,000-resample paired cluster bootstrap; lower 95% bound >= -0.01 |
| graph mapping gain | not_run | paired mapping-subset bootstrap; lower 95% bound > 0 |
| deployment authorization | not_run | explicit implementation-session/operator authorization |

Synthetic/recorded fixtures establish mechanics only. A missing service, model, judged
label set, or target runtime remains not_run/not_comparable/inconclusive and cannot be
converted into a pass by a fixture.

## Milestones

MVP-A, MVP-B, and MVP-C are all HOLD while the matrix above contains unresolved gates.
Authorization policy, publication recovery, backend isolation, secret handling,
freshness/lifecycle, matched content, retrieval parity, predecessor correctness, and
rollback mechanics are release-blocking even when retrieval scores are high.

MVP-B additionally requires real OpenCTI, Milvus, and Neo4j evidence. MVP-C additionally
requires judged quality, the preregistered confidence-interval gates, and explicit
deployment authorization.

## Operational evidence

The comparison report records:

- direct normalization/chunking time and serialized content bytes;
- OpenCTI ingestion rebuild and wall time;
- state/storage bytes;
- ingestion/update lag;
- checkpoint and reconciliation state;
- cold and warm retrieval p50/p95, repeat counts, errors, and concurrency;
- fixed top-k, pre-rerank limit, context budget, lexical settings, query-split hash,
  ANN settings, and model availability.

The report does not claim throughput from sequential latency samples.

## Equal corpus versus enriched OpenCTI

The matched I1 experiment is the platform-attribution experiment. Any enriched OpenCTI
corpus is a separate coverage experiment with its own artifact hash and is never merged
into the matched comparison.

## Restricted evidence and RuntimePolicy

Benchmark artifacts must not disclose credentials or restricted raw captures. Restricted
reports are not publication-safe by default. Retrieval evidence, citation validity,
retrieval scores, or graph paths cannot authorize tools or change policy. RuntimePolicy
remains an injectable external authorization boundary rather than a Prompt 22
cross-repository dependency.

## Legacy availability

Prompt 22 adds code beside the legacy path. It does not modify the protected legacy
retriever/knowledgebase/graphbase/entity-extractor files, benchmark/query_test.py,
legacy collections, session/MQ behavior, model providers, or legacy API response
contracts. No automatic default switch is performed.

## Extraction decision

Decision: DEFER EXTRACTION.

Reconsider a generic repository only after all of the following are true:

1. CTI reaches MVP-C under real evidence rather than fixture-only mechanics.
2. A materially different second domain, preferably networking, is implemented
   end-to-end.
3. A documented review finds duplicated implementation in at least two shared contract
   layers that cannot be eliminated by local composition.

Until that trigger occurs, the advanced CTI implementation stays repository-local.
