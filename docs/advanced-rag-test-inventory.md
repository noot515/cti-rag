# Advanced RAG P00/P01 test inventory

Baseline revision: `15f4050a387bf41b8d77daf05e271ccfe9e522da`.

## Baseline discovery risks

The reviewed repository mixes historical `*_test.py` modules with `test_*.py` modules. The prior pytest configuration only discovered the first naming convention. Three files require explicit handling for an offline default gate:

- `tests/test_ner.py`: syntactically incomplete at the reviewed baseline and performs HTTP work at module import; ignored by default.
- `tests/test_milvus_fix.py`: executable live-Milvus script whose imports reach service code; ignored by default.
- `tests/model_router_test.py`: installs replacement `packages` modules into `sys.modules` during collection and requires Redis; ignored by default and intended for a separate explicit process when Redis is available.

`test_redis_runtime.py` and `test_redis_session.py` are marked `integration`; `test_original_error.py` is marked `legacy_service`. They are also explicitly ignored by the default offline command so collection cannot instantiate live dependencies before marker deselection. Default offline execution additionally filters `integration`, `legacy_service`, `opencti`, `gpu`, and `live_model` markers.

## New pure suites

- `tests/unit/evidence/test_imports.py`: real fresh-process package/evidence/CTI imports, no socket connection, no new files, no background thread, no implicit service/model imports, lazy executor/config behavior.
- `tests/unit/evidence/test_config.py`: disabled fixture defaults, strict nested validation, bounded settings, environment precedence, no Tavily activation, no remote provider/factory in fixture mode.
- `tests/unit/evidence/test_contracts.py`: canonical identity, UTC/JSON safety, serialization, relation multiplicity, chunk/path revision and traversal identity.
- `tests/unit/evidence/test_policy.py`: deny-by-default, explicit public fixture scope/source/destination checks, unresolved/granular/TLP restriction denial.
- `tests/unit/cti/test_cti_contracts.py`: typed fixture normalization, identifier parsing, exact keys, domain-adapter authorization separation, reviewed graph patterns, CTI markings, relation multiplicity, report-reference semantics and cross-domain non-merge.
- `tests/unit/cti/test_fixture_validation.py`: synthetic marker required and unreviewed relation rejection.

Executed in the sandbox with Python 3.13.5:

```text
python -m pytest tests/unit/evidence tests/unit/cti -q
41 passed
```

The required repository runtime is Python 3.11. It is not installed in this sandbox, so an exact 3.11 run remains `not_run`. Full-repository collection also remains `not_run` because direct GitHub cloning is unavailable in the execution sandbox; source/test inventory was obtained from the authenticated repository tree instead. These limitations do not convert into passes.
