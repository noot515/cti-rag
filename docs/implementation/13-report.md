# Phase 13 implementation report — point-in-time financial evidence and reproducible calculations

Status: **own deterministic gate passed; cumulative acceptance remains blocked by live SEC/FRED, licensed market-data entitlement, and inherited external gates**

## Lineage and fingerprints

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/12-report.md`
- Validated Phase 12/13 checkpoint: `50780dbc1b22a26591073d1fe9455208580e4552`
- Finance fixtures: `7652a8d95336f71f530484638ce260619b824aaf`
- Source adapters/normalizers: `9bbf97907c99173d5bc3a339bbcdcbf4c236c11e`
- Structured schemas: `b41d38dd7351e2d9cc3282c15300696bc158f873`
- Projection layer: `b9d7bf89fa81f73028885953de3c7183345496f2`
- Ticker resolver: `0c61db78c49088ec203520c42a63628afe819030`
- Calculation engine: `480bab02a07d0641e573093c63192c2ee868a836`
- Source readiness registry: `b5740dbeeb1406c47d3d42322e7ba8b4a9e7a6c6`
- DomainSpec: `60aa019bff21330846376b1a8f28b95faf84e4b8`
- Quant test blob: `d9ede0bb004091e281f7f99c3c66b145a4f3359d`
- Shared structured compiler: `c64eaaf09242f9fae1510968f6504082b359d0da`
- Validation registry: `21ca5c2ffa337ffda1d225e0d85621c14092df95`
- Workflow: `da090a5c0922b2690c29f1831768ac834b048acf`
- Existing config fingerprint: `a90848b9f9884c344d3fe2cc10cd6ec8c13da591`
- Model fingerprint: **none; Phase 13 deterministic gates invoke no model**

## Implemented

### SEC filing/XBRL-shaped evidence

The offline SEC-shaped fixture distinguishes issuer CIK from filing accession identity. Filing normalization preserves form, filing/acceptance availability, amendment metadata, document section coordinates, XBRL-like namespace/tag/context coordinates, value, unit, currency, reporting period and reporting basis.

Company and filing identities project into exact retrieval. Filing document sections project into lexical/dense-compatible passages using canonical section coordinates. Filing → issuer and amendment relationships are explicit source-backed graph assertions.

### FRED/ALFRED point-in-time macro vintages

Each macro observation preserves series ID, observation date, value, unit, frequency, seasonal adjustment, realtime/vintage start/end and source coordinate. The stable logical observation key is series/date while revisions differ by vintage/content. The existing Prompt 09 structured engine selects the latest eligible vintage at the requested public-knowledge cutoff.

### Licensed-file price and corporate-action adapters

Synthetic CSV file-import adapters model provider, security ID, ticker, exchange, trading date, close, currency, market calendar, timezone, adjustment flag, corporate-action version and availability.

A later adjusted-price file is a new immutable revision of the same logical security/date/provider row. Because revision selection happens inside the shared temporal structured engine, that later corporate-action adjustment is excluded from earlier strict historical queries.

The fixtures demonstrate import mechanics only. They do not imply credentials, contractual entitlement, market-feed completeness, or access to any production licensed provider.

### Security identity, ticker aliases and universes

Issuer, security, exchange and ticker alias intervals remain separate. `TickerAliasResolver` requires ticker, exchange and timezone-aware point in time and rejects ambiguous/missing joins.

Fixtures include a ticker reused by two securities on the same exchange across non-overlapping intervals, plus a delisted security that remains a member of the historical universe before delisting. Current membership is therefore not substituted for historical membership.

### Returns and event study

`QuantCalculationEngine` first retrieves point-in-time prices using the existing structured engine; it does not bypass revision/vintage selection.

Simple returns use declared close-to-close arithmetic and validate common currency, calendar, timezone and adjustment basis.

`EventStudySpec` records:
- target security;
- benchmark;
- event date;
- estimation window;
- event window;
- return definition;
- missing-data rule;
- provider;
- currency;
- calculation version.

The deterministic market-model calculation estimates alpha/beta from the estimation window and returns abnormal return/CAR as a verified `StructuredResult`. All input revision UIDs, provenance locators, input manifests, snapshot context and output units are retained. The result label explicitly states that the association is not a causal or profitability claim.

### Readiness registry

Fixture validated:
- SEC filing/company/fundamental/disclosure mechanics;
- FRED/ALFRED vintage mechanics;
- licensed-file price/corporate-action import mechanics;
- security-master/ticker/universe mechanics.

Deferred:
- earnings material;
- research corpora/provider rights.

## Validation actually executed

GitHub Actions run `35851684023`, job `107150607851`, Python 3.13.15:

- cumulative deterministic Phase 01–13 unittest suite: **126/126 passed in 6.849 s**
- Phase 13 quant gate: **6/6 passed in 1.886 s**
- affected legacy API/runtime regressions: **8/8 passed**
- fail-closed validation-registry audit: **passed**, while the registry's overall status correctly remains `fail`.

Phase 13 verifies:
- original SEC filing/XBRL-shaped and FRED/ALFRED-shaped source coordinates survive normalization;
- company CIK and filing accession exact lookup;
- cited filing-section retrieval;
- a later SEC amendment does not leak into an earlier cutoff;
- a later macro vintage does not leak into an earlier cutoff;
- a future corporate action does not leak into an earlier cutoff;
- later adjusted prices do not replace unadjusted historical-public prices before availability;
- simple return fixture includes an independently known 5% return;
- event-study fixture produces alpha = 0, beta = 2 and event CAR = 3%;
- ticker reuse resolves by exchange/time;
- a delisted security remains visible in its historical universe interval;
- unknown financial units are rejected;
- output `presentation_limit=1` does not change a full-corpus row-count aggregate (10 rows).

## Explicit blockers

`phase13-live-sec-fred-lifecycle` is **blocked**: no live EDGAR/FRED/ALFRED network/API amendment/vintage reconciliation was executed.

`phase13-licensed-market-data-entitlement` is **blocked**: no production market-data credentials, licensed provider entitlement or feed was supplied. Synthetic licensed-file fixtures cannot satisfy that gate.

## Migration and rollback

No live brokerage, market-data, SEC or FRED account was accessed and no production corpus/index was mutated. New finance evidence uses the existing immutable ingestion, snapshot, structured and graph boundaries. The advanced retrieval route remains disabled by default. Rollback is commit/snapshot reversal without deleting preserved prior source revisions.
