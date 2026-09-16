# Advanced RAG V3 implementation status

Updated: 2026-09-16. Reviewed application baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`. Prompt 02/03 head: `d210c0fde63df3ed765e0310f699f913722947d4`. Prompt 04 documented head: `19f7e6fe86fd6e3eb5b61cb6ece9d44143482bac`. Prompt 05 implementation commit: `fc439d7fb62733b359df2c305b43d96971e9bd78`. Current stacked branch: `feat/advanced-05-durable-evidence-catalog`. Legacy retrieval remains available and the advanced path remains disabled by default.

## P00-P03 predecessor state

The predecessor stack provides offline-safe configuration/import behavior, a reproducible L0 evaluation boundary, and generic evidence, provenance, policy, snapshot, candidate and channel contracts. The P00-P03 checkout was separately validated on Windows/Python 3.11, including full repository pytest collection.

## Prompt 04 - CTI normalization, identifiers, markings and synthetic corpus

Prompt 04 hardened the existing CTI domain package rather than duplicating it:

- deterministic LLM-free CTI object/assertion normalization;
- typed STIX family/type/id, lifecycle, nullable confidence and marking metadata;
- strict CVE/CWE/CAPEC/ATT&CK parsing plus validated IP/hash/domain observables;
- aliases as ambiguous candidates only, never exact identity;
- report `object_refs` as explicit non-causal reference assertions;
- quarantine counts/reasons for malformed, unsupported, dangling or policy-unresolved records;
- unresolved markings, unsupported granular selectors and non-contractual unmarked data fail closed;
- synthetic three-hop mapping mechanics, report/distractor/restricted records, multilingual queries, and physically separate qrels/path annotations.

The Prompt 04 sandbox correctness gate passed (`28 passed`) plus compile/diff checks. Exact Prompt 04 Python 3.11/full-repository collection remains separately `not_run` on the new checkout.

## Prompt 05 - durable raw payloads and scoped revision catalog

Implemented under `packages/evidence/` without modifying legacy MySQL tables or tracked legacy databases:

- `RawPayloadStore` writes content-addressed bytes to a private temp file, flushes/fsyncs, atomically renames, verifies existing/published bytes, and uses restrictive permissions where the platform supports them;
- `EvidenceStore` is explicitly constructed and has no import-time database/service connection. It uses SQLite WAL, `foreign_keys=ON`, `synchronous=FULL`, explicit migration versioning, transactions, and a cross-process single-writer lock;
- catalog tables cover raw payloads and source identity, object/relation revisions, chunks, exact external-ID mappings, snapshots/membership, index jobs, backend acknowledgements, checkpoints, tombstones, poll observations and explicit evidence equivalences;
- physical primary/foreign keys include `domain` and `scope_id`, allowing identical logical UIDs in separate scopes without cross-scope joins;
- semantic revision payloads are immutable. A duplicate revision with different semantic payload raises rather than overwriting; polling/capture observations are stored separately;
- source evidence links retain source instance/object, raw digest, source snapshot and normalizer version. Exact identifiers remain many-to-many;
- raw bytes are published before the catalog transaction, so a crash can leave only an unreferenced orphan raw file; no catalog row/checkpoint points to absent bytes;
- checkpoint updates share the catalog transaction with batch persistence. Foreign-key or immutable conflicts roll back without advancing the checkpoint;
- storing a snapshot records it inactive (`active=0`); this phase provides no activation/publication method;
- replaying an identical batch yields zero logical catalog changes;
- `get_revision`, `list_scoped_revisions`, `get_assertion`, `get_chunk` and `resolve_external_ids` are scope/domain explicit;
- raw digest metadata lookup and hydration first require a trusted resolved scope, policy authorization and an evidence-to-raw linkage. Unauthorized callers cannot use the raw store as a digest-existence oracle;
- the advanced store imports neither `packages.manager.kb_db_manager` nor legacy SQLAlchemy/PyMySQL modules; legacy database initialization remains isolated from this path.

No Milvus/Neo4j projection, active snapshot publication, legacy `knowledge.db` migration, garbage collection, OpenCTI sync, retrieval orchestrator or service promotion is implemented here.

## Prompt 05 validation

Available sandbox interpreter: Python 3.13.5 with Pydantic 2.13.4. Repository runtime target remains Python 3.11.

```text
PYTHONPATH=. python -m pytest tests/unit/evidence/test_store.py tests/unit/evidence/test_raw_store.py -q
12 passed

PYTHONPATH=. python -m pytest tests/unit/cti tests/unit/benchmark/test_data_boundary.py tests/unit/evidence/test_store.py tests/unit/evidence/test_raw_store.py -q
40 passed

PYTHONPATH=. python -m compileall -q packages benchmark tests/unit
passed

git diff --check
passed
```

The exact Prompt 05 branch has not yet been rerun under Python 3.11 or through full repository collection in this environment. Those gates are `not_run`. SQLite tests are local/offline; no real OpenCTI, Milvus, Neo4j or live-model/service test was run, and no retrieval-quality score is claimed.

## Next-phase readiness

Prompt 06 may begin only after the Prompt 04/05 stacked diff is reviewed and the intended Python 3.11/full-checkout correctness gate is rerun. Storage does not activate a snapshot or authorize backend publication by itself.
