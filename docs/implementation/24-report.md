# Phase 24 release-readiness report — accumulated conformance, migration, and handoff

Status: **fixture-core milestone passed; text-MVP, five-domain, and full-release milestones remain blocked**

## Lineage and validation

- Parent implementation report: `docs/implementation/23-report.md`
- Parent documented head: `760197338e46c9c4d03e7da086ed2bf539c68515`
- Validated Phase 23/24 code checkpoint: `4a62bc06d64204ccfb72c9fcd55d7b086cb799a3`
- Actions run/job: `36134108297 / 108067939377`
- Python: **3.13.15**
- Cumulative deterministic suite: **203/203 passed in 31.308 s**
- Phase 23 invariant gate: **6/6 passed in 0.041 s**
- Phase 24 conformance/migration gate: **5/5 passed in 0.208 s**
- Affected legacy API regressions: **8/8 passed**
- Cumulative validation registry through Phase 24: **verified successfully while intentionally fail-closed**

The registry executes all accumulated deterministic/contract gates and preserves required blocked real-service/model/human-review gates rather than marking them optional.

## Revised-plan conformance

`validation/revised-plan-conformance.json` accounts for **every revised-plan section 1–25 exactly once**, mapping each section to code, test/status evidence, status, milestone group, and blocking reason when applicable.

Current computed milestone status:

| Milestone | Status | Blocking revised-plan sections |
| --- | --- | --- |
| fixture core | **passed** | none |
| text MVP | **blocked** | 19, 20, 21 |
| five-domain | **blocked** | 16, 18, 21 |
| full release | **blocked** | 16, 17, 18, 19, 20, 21, 25 |

A lower-level passing milestone is preserved even when a larger milestone is blocked.

## Source readiness

`validation/source-readiness.json` inventories **48 source/source-family entries** and does not equate a registry/manifest entry with a working adapter.

| Domain | Inventory | Adapter + fixture lifecycle passed | Live lifecycle passed |
| --- | ---: | ---: | ---: |
| cybersecurity | 20 | 4 | 0 |
| networking | 10 | 5 | 0 |
| quant | 9 | 7 | 0 |
| humanities | 8 | 3 | 0 |
| privacy | 1 | 0 | 0 |
| **Total** | **48** | **19** | **0** |

The privacy domain currently has a specification but no source registry/manifest, source adapter, or fixture lifecycle comparable to the other four domains. This is an explicit five-domain blocker.

Registered/deferred sources such as NVD/GHSA and several humanities/networking sources remain labeled adapter `blocked` / fixture `not_run`, not operational.

## Isolated migration rehearsal

`scripts/phase24_migration_rehearsal.py` performs the requested migration sequence against real local snapshot/catalog/SQLite FTS5/recovery primitives in an isolated data root:

1. create and publish a legacy lexical generation;
2. query the legacy generation and observe the expected result;
3. confirm advanced retrieval is disabled and legacy endpoints enabled by default;
4. create/publish a new lexical generation;
5. enable the advanced-retrieval feature flag and observe the new-generation query result;
6. atomically roll back to the serviceable legacy manifest and re-query;
7. re-publish the new generation;
8. tombstone the returned passage and verify current revocation makes the query empty;
9. create a backup;
10. restore into a separate isolated root;
11. verify current manifest and revocation survive restoration.

The rehearsal does not deploy externally or mutate user-running services.

## Optional integrations and protected access

The release tests confirm:

- advanced retrieval defaults disabled;
- web overlay defaults disabled;
- legacy endpoints remain enabled for compatibility;
- OpenCTI is not required for the local core;
- external RuntimePolicy is not required for the explicit local/public-only core mode;
- local public-only policy refuses a requested private scope rather than enabling it through a permissive placeholder.

Optional OpenCTI/web/RuntimePolicy components can therefore be absent without corrupting the local fixture core. Their live validation gates remain separately blocked.

## Build/config/corpus/model identity

- code checkpoint: `4a62bc06d64204ccfb72c9fcd55d7b086cb799a3`
- Phase 21 corpus: `phase21-dev-v1`, 779 corpus records / 280 queries
- Phase 21 deterministic report digest: `0792ec472861f1e8a9ad343c0ffa6e351b46c198f6eaee0236dfe24a25a5d14e`
- Phase 23 production retrieval config: `baseline-v1`
- Phase 23 tuning candidate: `bulk-hydration-32`, **not promoted**
- real-model evaluation fingerprints: **none available; required gates blocked**
- conformance matrix blob: `15451b121559b7a63ed6e546b1690b610ff6ee4a`
- source readiness blob: `359ad811491d0d998ad670bd74426ab195859a95`
- release conformance code: `c3a5b5464fbff52b1c9adeb9aa40708687c85da4`
- migration rehearsal: `b5efad8010a06b4cebbc7ab744b8e4c98179affe`
- Phase 24 tests: `3c7e54538f8a1dc7fbfcd3ed38bf3a86324c9701`
- cumulative validation registry: `19dc755d9171da6c06872ef0674c691c506c14bb`
- CI workflow: `6f92365b0538c8bd962a4b27a5ab26d9b6ca14c7`

## Reproducible local commands

Minimal fixture/profile example:

```bash
export CTI_RAG_DATA_ROOT="$PWD/.cti-rag-local"
python scripts/phase22_profile_smoke.py \
  --profile deploy/profiles/fixture.json \
  --root "$CTI_RAG_DATA_ROOT/profile"
```

Migration/query/rollback/restore rehearsal:

```bash
python scripts/phase24_migration_rehearsal.py \
  --root "$CTI_RAG_DATA_ROOT/migration" \
  --backup "$CTI_RAG_DATA_ROOT/backup" \
  --report "$CTI_RAG_DATA_ROOT/migration-report.json"
```

Release conformance report:

```bash
python scripts/run_phase24_conformance.py \
  --report "$CTI_RAG_DATA_ROOT/conformance-report.json"
```

Full operator walkthrough: `docs/operators/local-fixture-example.md`. Deployment/recovery commands remain in `docs/operators/deployment-recovery.md`.

## Mandatory blockers and smallest next actions

1. **Phase 14 required prerequisite:** implement and execute the missing phase rather than bypassing it.
2. **Privacy source lifecycle:** define at least one redistributable/public privacy source manifest + adapter + normalization/citation lifecycle and execute its fixture gate; until then the five-domain milestone remains blocked.
3. **Real model quality:** run approved pinned embedding, reranker, and generator/grounding evaluations on the frozen Phase 21 set with model fingerprints.
4. **Human review:** add reviewed pooled judgments with reviewer provenance; do not relabel machine-generated judgments.
5. **Real performance:** run baseline-v1 versus the single tuning-selected bulk-hydration candidate under comparable real backend/model load and preserve the held-out selection protocol.
6. **Live backends/sources:** execute the required MySQL/Milvus/Neo4j/source lifecycle and staging deployment gates already named in `validation/gates.json`.
7. **Live optional integrations:** only required for milestones that claim those integrations; OpenCTI/web/RuntimePolicy remain disabled/blocking where applicable.

## Release decision

The **fixture-core milestone is release-ready for its explicitly limited local fixture scope**.

The **text-MVP, five-domain, and full-release milestones are not release-ready**. No universal correctness, privacy, freshness, or speed guarantee is claimed from the finite deterministic evidence. No production deployment or external communication is authorized by this phase.
