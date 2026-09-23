# Phase 12 implementation report — networking identifiers, observations, and retrieval

Status: **own deterministic gate passed; cumulative acceptance remains blocked by live networking-source and inherited external gates**

## Lineage and fingerprints

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/11-report.md`
- Validated Phase 12/13 checkpoint: `50780dbc1b22a26591073d1fe9455208580e4552`
- Networking fixtures: `d51296b5d253be40825b03000b1dc18824b7750c`
- Source adapters/normalizers: `f638576d4b48f218965d5f7b7deddbb05161c9d6`
- Structured schemas: `6f8dbcd5d506f6a15eadbc4df2f38603eb2e41b0`
- Projection layer: `0276139a584969f0fcf92e7f9ac01bc32d4d619c`
- Source readiness registry: `18950b7124b6065768bd5539d7fa2acbff591e8f`
- Snapshot import/export/replay: `bba7c43e8e0ca65823a5ef63407fb8d2055ea49c`
- DomainSpec: `c9cbddfcccc3a62f653c54d5978efc3548ea45f2`
- Networking test blob: `fd05a088ee386e878ff9942523a7ede86b820b39`
- Shared structured compiler: `c64eaaf09242f9fae1510968f6504082b359d0da`
- Shared identifier registry: `0e2767114c2d3b90466ffc3069843425069e6202`
- Shared GraphPort: `75b3bc0770020f69a44ca73b1d89d84dd3328b5b`
- Validation registry: `21ca5c2ffa337ffda1d225e0d85621c14092df95`
- Workflow: `da090a5c0922b2690c29f1831768ac834b048acf`
- Existing config fingerprint: `a90848b9f9884c344d3fe2cc10cd6ec8c13da591`
- Model fingerprint: **none; Phase 12 deterministic gates invoke no model**

## Implemented

### RFC document evidence

RFC fixtures normalize into immutable RFC objects with RFC-number identity, publication time, section structure, and updates/obsoletes metadata. Exact lookup returns the preserved RFC even when obsolete and reports its obsolescence rather than deleting/replacing the older document. Explanatory passages use section-level canonical locators such as `RFC 4271#4.3`; lexical/dense compatibility is inherited from the normal passage projection path.

RFC updates and obsoletes are graph assertions with source support. They are not inferred from section similarity.

### BGP, RPKI, DNS, and RDAP semantics

BGP observations record prefix, collector, vantage point, peer ASN, observed origin ASN, AS path, observation interval, and source availability. The structured logical key contains collector/vantage-relevant identity so two collectors may disagree without overwriting each other.

RPKI records represent authorization separately through prefix, maximum length, authorized ASN and validity interval. Graph semantics use `authorized_origin`.

RDAP records represent registration separately through `registered_to`.

DNS answers retain resolver/vantage point, observation time and TTL-derived validity and remain structured observations only. No DNS answer becomes an ownership assertion.

### IPv4/IPv6 containment and longest prefix

The shared `IP_IN_PREFIX` compiler now supports schemas whose range bounds are fixed-width 128-bit hexadecimal strings and optionally include an IP-family column. This preserves the previous integer IPv4 fixture and permits IPv4/IPv6 matching without enabling backend-specific network extensions.

The networking BGP/RPKI/RDAP schemas store canonical prefix, family, prefix length, start and end bounds. Longest-prefix match is a typed containment query ordered by prefix length after eligibility filtering.

### Graph request semantics

The GraphPort now enforces the requested relation set during traversal. A request for `announced_by` cannot also emit `registered_to` or `authorized_origin` edges simply because the same prefix participates in all three.

Canonical entity visibility is policy/revocation based while source/time eligibility remains assertion-specific. This allows a single canonical prefix to be supported by multiple networking sources without whichever projection was deduplicated first controlling source filtering.

### Snapshot replay and source readiness

Small networking source records support checksumed export/import/replay. BGP corrections create new immutable revisions rather than mutating the older observation.

Readiness is explicit:
- fixture validated: RFC, BGP/RIS-shaped observations, RPKI authorization, DNS observations, RDAP registration;
- deferred: bulk RIR registration, configurations, packet/event metadata, certificates, topology.

## Validation actually executed

GitHub Actions run `35851684023`, job `107150607851`, Python 3.13.15:

- cumulative deterministic Phase 01–13 unittest suite: **126/126 passed in 6.849 s**
- Phase 12 networking gate: **6/6 passed in 0.588 s**
- affected legacy API/runtime regressions: **8/8 passed**
- fail-closed validation-registry audit: **passed**, while the registry's overall status correctly remains `fail` because required external gates are blocked.

Phase 12 verifies:
- RFC exact lookup and obsolete status;
- section-level RFC citation for RFC 4271 §4.3;
- IPv4 longest-prefix match (`203.0.113.200` → `203.0.113.128/25`);
- IPv6 longest-prefix match (`2001:db8:1::1234` → `2001:db8:1::/48`);
- missing-route result remains empty;
- two collectors preserve disagreeing route origins;
- later BGP corrections and later BGP/DNS observations do not leak into earlier historical-public cutoffs;
- announcement, RPKI authorization, and registration remain different graph relations;
- snapshot export/import/replay is content-stable and checksum protected.

## Explicit blocker

`phase12-live-network-source-lifecycle` is **blocked**. CI did not run live RFC Editor reconciliation, RIPE RIS collection, a live RPKI repository/validator, or production DNS/RDAP source lifecycle. The small fixtures prove source/temporal/retrieval mechanics only.

## Migration and rollback

No live networking corpus or production backend was modified. The domain composes through existing SourceConnector/Normalizer, exact/lexical, StructuredPort, GraphPort, snapshot and revocation contracts. Rollback is commit/snapshot reversal; immutable source observations remain addressable according to existing retention policy.
