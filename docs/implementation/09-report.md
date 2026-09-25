# Phase 09 implementation report — structured analytics and temporal evidence eligibility

Status: **implementation/own real-DuckDB gate passed; cumulative promotion remains blocked by inherited external gates**

## Lineage and fingerprints

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/08-report.md`
- Validated Phase 08/09 code checkpoint: `6c0e5b0f53ddedf15b4da5f4bcbfb87d04fdbc6f`
- Structured contracts: `874361de0ec836d2f00b1fe0ec4d86b42307564e`
- Safe compiler: `fdb1e5c9508ed90c84244a797415e51ce35aeac8`
- DuckDB port: `c3b0299f1c2a88fc66e0aed7b664873ba7ad3793`
- Analytical fixtures: `307693089fb4c0013fac726cd8365517ae96b90b`
- Extended StructuredResult contract: `c342094b455527a9ee702d3c574ca5d9a80bc610`
- Phase 09 test blob: `4c9df33efc4a9f1acb7afbd81da2a6c68008ca5f`

## Implemented

A server-owned `DatasetRegistry` defines dataset/table names, typed fields, units/nullability, logical revision keys, revision order, temporal columns, system-manifest columns, dependency eligibility fields, data-snapshot identity, and allowlisted join keys. Clients cannot supply physical table names outside the registry.

`StructuredQuerySpec` supports typed predicates, bounded joins, grouping, allowlisted COUNT/SUM/AVG/MIN/MAX aggregations, ordering, presentation limits, valid-time points, and explicit unknown-availability policy. Values are parameterized. Raw SQL, arbitrary paths, unknown datasets/fields, unrestricted functions, invalid IP values, and non-allowlisted joins fail validation.

The validated DuckDB profile uses in-memory/preloaded server-owned tables. The connection disables external access and unsigned extensions and applies memory, thread, scan-row, and wall-time bounds. DuckDB is now a runtime dependency in `requirements-api.txt`. The query compiler applies authorization and temporal predicates before revision selection and aggregation. Presentation `LIMIT` is applied only after full eligible-set aggregation, so output rows cannot redefine count/sum semantics.

Temporal modes now differ explicitly:
- current evidence selects the latest eligible source revision for each logical key;
- historical-public knowledge excludes unknown availability (or rejects according to the query policy), requires availability at/before cutoff, applies dependency availability, and then chooses revision precedence;
- historical-system replay requires the requested system manifest and compatible dependency manifest.

Optional valid-time filters are applied separately from availability/system time. Derived rows can be unavailable if their dependencies were not yet eligible.

`StructuredResult` additively records dataset snapshot, query-spec hash, typed fields with units/nulls, temporal mode, calculation fingerprint/version, revision-level provenances, and a reproducible input-set manifest. Verified structured output is kept in the context packer as a typed obligation and never fed into passage RRF.

Public deterministic fixtures cover revised macro observations, late ingestion, unknown availability, dependency availability, 120-row vulnerability analytics, null numerical values, and IPv4 prefix containment using precomputed numeric prefix ranges rather than an externally loaded DuckDB network extension.

## Validation actually executed

GitHub Actions run `35839225054`, job `107110015621`, Python 3.13.15, with an actual DuckDB 1.x package installed by the workflow.

- cumulative Phase 01–09 unittest suite: **98/98 passed in 4.228 s**
- Phase 09 own gate: **11/11 passed in 3.115 s**
- affected legacy API/runtime regression: **8/8 passed**
- cumulative registry: expected overall `fail` solely because required inherited/external gates remain blocked.

Phase 09 fixtures verify:
- COUNT across all 120 eligible vulnerability rows is computed before `presentation_limit=1`;
- typed numerical CVSS filtering produces reproducible result/query/input fingerprints;
- a later macro revision cannot leak into an earlier public-knowledge cutoff;
- public-knowledge and historical-system-replay differ for late ingestion;
- unknown availability is conservatively excluded or explicitly rejected;
- dependency availability participates in strict historical eligibility;
- null values and units survive unchanged;
- IP prefix containment returns the correct registered prefix without extension/network access;
- raw SQL, filesystem-path, function, and field injection attempts are rejected;
- scan budget is independent of output-row limit;
- verified structured results remain typed outside passage RRF.

## Limitations and migration

The validated profile intentionally uses preloaded tables, which is one of the authoritative design's approved DuckDB modes. No client-selectable Parquet path is exposed. Production onboarding of approved Parquet snapshots will require a server-owned path registry plus lifecycle/restore tests, not a widening of `StructuredQuerySpec`.

No graph analytical joins, event-study finance template, or large-scale Parquet benchmark is claimed by this phase. Those are later domain/onboarding work. The new retrieval/API route remains disabled by default, and cumulative milestone promotion remains blocked by the pre-existing external gates.
