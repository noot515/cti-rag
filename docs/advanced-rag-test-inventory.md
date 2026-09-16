# Advanced RAG P00-P03 test inventory

Baseline revision: `15f4050a387bf41b8d77daf05e271ccfe9e522da`. Prompt 02/03 predecessor: `312e11837bde5b525d277bf7387c57ce30487bb3`.

The default offline gate continues to isolate historical live/service/stub-heavy tests identified in P00. Prompt 02/03 adds only pure unit suites and a network-free CLI preflight.

## New Prompt 02 suites

- `tests/unit/benchmark/test_data_boundary.py`: query/qrels separation, nested evaluation-field rejection, path traversal rejection, corpus hash/schema pinning, QA-shaped corpus rejection, and honest metric status serialization.
- `tests/unit/benchmark/test_legacy_adapter.py`: required `user_id`, forced web-off request, stream assembly, observed route metadata, timeout-as-failure behavior, denominator preservation and network-free preflight/report writing.

## New/updated Prompt 03 suites

- `tests/unit/evidence/test_ids.py`: golden canonical IDs, revision-projection stability across repeated captures, policy/marking revision changes, stable logical object IDs, reverse traversal identity and scope-qualified physical keys.
- `tests/unit/evidence/test_schema.py`: discriminated candidate round trips, wrong-scope rejection, duplicate-channel rejection, finite score validation and pinned path-node revisions.
- `tests/unit/evidence/test_contracts.py`: predecessor identity/UTC/relation/path tests updated for required snapshot/node-revision pinning.
- `tests/unit/evidence/test_policy.py`: predecessor denial/marking tests plus trusted fixture-policy construction, unknown/provider destination denial and fail-closed compound/path authorization.
- `tests/unit/retrieval/test_candidate.py`: `BackendHit` cannot masquerade as an authorized candidate; channel boundary signature/status behavior.

Executed in the sandbox with Python 3.13.5:

```text
python -m pytest tests/unit/benchmark tests/unit/evidence tests/unit/retrieval -q
33 passed
```

`python -m compileall -q packages benchmark/advanced tests/unit` also passed. The required Python 3.11 run and full repository collection remain `not_run` because the interpreter/full clone are unavailable in this sandbox. No service/model/quality gate is inferred from these pure tests.
