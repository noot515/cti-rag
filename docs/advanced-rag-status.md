# Advanced RAG V3 implementation status

Updated: 2026-09-16. Reviewed application baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`. Prompt 02/03 predecessor: `312e11837bde5b525d277bf7387c57ce30487bb3`. Current stacked branch: `feat/advanced-03-generic-evidence-contracts`. Legacy retrieval remains available and the advanced path remains disabled by default.

## P00/P01 predecessor state

The predecessor branch provides offline-safe advanced configuration/import behavior plus initial generic evidence and CTI contracts. Prompt 03 reconciles and strengthens those generic contracts instead of creating duplicate definitions.

## Prompt 02 - baseline and evaluation boundary

Implemented under `benchmark/advanced/`:

- strict `CorpusManifest`, `QueryRecord`, evaluation-only `QrelRecord`/`AnnotationRecord`, source-lineage and file-hash contracts;
- path traversal, changed-hash, schema-version and QA-shaped corpus rejection;
- ground-truth fields are excluded from `QueryRecord` and recursively forbidden in `options`, so qrels/answers cannot cross the retrieval request boundary accidentally;
- `MetricResult` explicitly distinguishes `not_run`, `not_applicable`, `not_comparable` and `inconclusive`, and unavailable values serialize as `null`;
- structured `L0RunConfig`, `QueryRunRecord` and `BaselineRunReport` with failures retained in the denominator;
- an L0 legacy HTTP adapter that supplies the required `user_id`, forces `use_web=false`, assembles stream chunks, records observed model routing metadata, and converts timeouts/HTTP failures into failed queries rather than answer text;
- reproducible legacy config plus frozen synthetic/public corpus and query manifests;
- `--preflight-only` mode validates manifests/config and writes an honest report without network access.

No baseline quality score is claimed. Without a separately verified canonical legacy-object mapping, the L0 object metric is `not_comparable`. Answer-quality metrics remain `not_run` in this phase.

## Prompt 03 - generic evidence/channel contracts

Reconciled the predecessor generic layer so there is one canonical definition for each contract:

- canonical `DomainAdapter`, `GraphPattern` and `NormalizedEvidenceBatch` now live in `packages/evidence/domain.py`; `packages/domains/base.py` is a compatibility re-export;
- versioned SHA-256 object/revision/relation/chunk/path identities remain canonical; scope-qualified `physical_key()` separates logical identity from backend storage identity;
- canonical revision projection explicitly includes meaningful source origin, normalizer version, semantic fields, policy and evidence locators while excluding polling/retry timestamps, source snapshot IDs and raw-byte formatting hashes;
- `SnapshotRef` and `EvidencePath` pin node revisions and snapshot scope;
- candidate contracts are a discriminated object/chunk/path union with target-object identity, scope/domain/snapshot, unique per-channel contributions, and finite optional fusion/rerank scores;
- `BackendHit` is intentionally not an authorized candidate;
- `ChannelResult` and `Channel.search(plan, scope, snapshot, deadline)` define the backend-independent channel boundary;
- canonical policy names are `Principal` and `ResolvedScope`; old `TrustedPrincipal`/`AuthorizedScope` names remain compatibility aliases;
- `PublicFixturePolicy` now requires trusted construction and an explicit non-empty source allowlist; unknown/provider destinations fail closed. `authorize_evidence_set()` fails closed unless every supplied node/assertion/support view is authorized, providing the compound/path authorization primitive required by later graph channels.

## Validation

Sandbox interpreter: Python 3.13.5. Repository target: Python 3.11.

```text
python -m pytest tests/unit/benchmark/test_data_boundary.py tests/unit/benchmark/test_legacy_adapter.py tests/unit/evidence/test_ids.py tests/unit/evidence/test_schema.py tests/unit/evidence/test_contracts.py tests/unit/evidence/test_policy.py tests/unit/retrieval/test_candidate.py -q
33 passed

python -m benchmark.advanced.legacy_adapter --config benchmark/advanced/configs/legacy.yaml --preflight-only --output saves/eval/l0-preflight
saves/eval/l0-preflight/report.json

python -m compileall -q packages benchmark/advanced tests/unit
passed
```

The exact Python 3.11 run, full-checkout collection, Milvus/Neo4j/OpenCTI/live-model tests and retrieval-quality gates remain `not_run`. The execution sandbox cannot resolve github.com, so full-repository runtime validation cannot be manufactured here.

## Next-phase readiness

Prompt 04 may begin after the stacked branch is reviewed/accepted. No storage catalog, snapshot publication, vector/graph projection, retrieval orchestrator, advanced API, OpenCTI sync or quality promotion is implemented by Prompt 02/03.
