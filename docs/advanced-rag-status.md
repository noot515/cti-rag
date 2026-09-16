# Advanced RAG V3 implementation status

Updated: 2026-09-16. Reviewed application baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`. Prompt 02/03 predecessor: `312e11837bde5b525d277bf7387c57ce30487bb3`. Prompt 04 predecessor: `d210c0fde63df3ed765e0310f699f913722947d4`. Current Prompt 04 branch: `feat/advanced-04-cti-domain-adapter`. Legacy retrieval remains available and the advanced path remains disabled by default.

## P00-P03 predecessor state

The predecessor stack provides offline-safe advanced configuration/import behavior, a reproducible L0 evaluation boundary, and generic evidence, provenance, policy, snapshot, candidate and channel contracts. Windows/Python 3.11 validation of the predecessor completed separately: the focused Prompt 02/03 suite passed, the combined P00-P03 suite passed, L0 preflight and compile validation passed, and full repository pytest collection completed without collection errors.

## Prompt 04 - CTI normalization, identifiers, markings and synthetic corpus

Implemented as a reconciliation/hardening pass over the CTI layer introduced before Prompt 04 rather than as a duplicate package:

- `CtiObject`, `CtiRelationship`, `CtiChunk` and `CtiNormalizedEvidenceBatch` remain typed extensions over generic evidence contracts; generic batches now also carry chunks for the storage boundary used by the next phase.
- CTI objects preserve STIX family/type/id, lifecycle flags, nullable producer confidence, source identity, marking references/definitions and granular selectors.
- normalization is deterministic and LLM-free; malformed or unsupported objects, assertions and report references are quarantined with explicit reason codes/counts rather than silently dropped;
- unresolved/unsupported markings suppress evidence; unsupported granular selector roots suppress the whole record; unmarked evidence is accepted only when the fixture/source contract explicitly sets `unmarked_data_public=true`;
- CVE, CWE, CAPEC and ATT&CK identifiers use strict boundary-aware parsing; IP observables use `ipaddress`, hashes use type/length checks, and domain observables are canonicalized and validated;
- aliases are exposed only through ambiguous candidate lookup and never inserted into exact identity keys;
- reviewed assertion kinds keep explicit/extracted/inferred/catalog mappings/references/equivalence distinct; embedded report `object_refs` become non-causal `references` assertions with field locators;
- synthetic corpus fixtures now include the three-hop CVE-2026-999999 -> CWE-79 -> CAPEC-66 -> T1059.001 mechanics chain, a report, T9999 distractor, a restricted fixture record, ambiguous aliases, and English/Chinese/mixed queries;
- qrels and path annotations are stored separately from corpus and query inputs. The synthetic mappings are mechanics fixtures, not factual catalog claims.

Path/contract reconciliation: the predecessor already contained `packages/domains/cti`; Prompt 04 strengthens it in place. The existing legacy L0 fixture is retained, with only its explicit unmarked-public source declaration added and its pinned SHA-256 manifest updated accordingly. Legacy entity extraction/retrieval code is unchanged.

## Prompt 04 validation

Available sandbox interpreter: Python 3.13.5 with Pydantic 2.13.4. Repository runtime target remains Python 3.11.

```text
PYTHONPATH=. python -m pytest tests/unit/cti tests/unit/benchmark/test_data_boundary.py -q
28 passed

PYTHONPATH=. python -m compileall -q packages benchmark tests/unit
passed

git diff --check
passed
```

The exact Prompt 04 checkout has not yet been rerun under Python 3.11 or through the repository-wide collection gate in this environment. Those gates are `not_run` for Prompt 04 and must not be inferred from the already-passing P00-P03 Windows validation. Live OpenCTI/model/service and retrieval-quality gates are also `not_run`.

## Next-phase readiness

Prompt 05 may begin from the Prompt 04 branch after its correctness diff is reviewed. Prompt 04 does not add a durable catalog, backend indexes, publication, retrieval orchestration, OpenCTI sync, advanced API routes, or quality promotion.
