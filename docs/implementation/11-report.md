# Phase 11 implementation report — cybersecurity source adapters and evidence lifecycle

Status: **core source fixture/lifecycle gate passed; live upstream lifecycle validation and inherited external gates remain blocked**

## Lineage and fingerprints

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/10-report.md`
- Validated Phase 10/11 code checkpoint: `d3395d26d9df72c60cea57e9d593b2b4901e68bc`
- Core connectors/normalizers: `0610c019de6c44b04a51c91512ad58a1731bfec6`
- Cyber projection layer: `8dd612944ca59848e873567dd479830c7a6b7b2d`
- Cyber structured schemas: `908e3f589b604bfe2bea2f9d185494632a2a9544`
- Source coverage registry: `2e5d7799b6ca490e364cea51997840320a5198d0`
- Real-format fictitious fixtures: `5a7abd1e88ba274ffc7b7f459d7dec7c51c2d394`
- Source lifecycle helper: `b08cde23173baa1c3f19f715d0d8741df4e7586b`
- Cyber benchmark cases: `827fc037ea169fe46d2aa116e9c9c363f601e3cc`
- Offline command surface: `8dc85e3e520c9fdc3f6c5fa0f35b0469ab6e9f29`
- Ingestion model contract: `70838fc611f52f464d9917c973860e8514eda503`
- Ingestion pipeline: `c224a1890b6881cc177101e7d66d67674a3517f3`
- Canonical metadata helpers: `a2fc616ca1e3f6026e3776eb819634658c75d4f7`
- Empty-generation SQLite lexical fix: `d19e85e13acbc17a4306e1801b1fe918ffd23b42`
- Empty-generation MySQL lexical fix: `f6a12f9e8542e3ba02c35a5d6e65fa69061f7ae0`
- Phase 11 test blob: `abe478a0f57b5e725ad3b32b64b4fbd41f46c732`

## Core adapters

### MITRE ATT&CK STIX 2.1

The adapter accepts STIX 2.1 bundle objects and validates supported object shapes. Attack-pattern records require a MITRE external technique ID and preserve STIX ID, name, description, version, created/modified availability, revoked/deprecated flags, policy/license metadata, and immutable source revision identity. Explicit STIX relationship records are projected only when both referenced graph endpoints resolve.

A later revoked/deprecated fixture produces a new preserved source revision and tombstones the retained ATT&CK object revisions through the shared current-revocation/cleanup lifecycle.

### CVE JSON 5.x

The adapter validates `CVE_RECORD` 5.x shape and preserves CVE ID, source dates, descriptions, explicit problem-type CWE mappings, and every CVSS assessment with scheme/version, vector, score, severity, and source container.

The fixture intentionally contains independent CNA and ADP CVSS 3.1 assessments. Current structured output retains scores 9.8 and 7.5 independently; the historical-public fixture before the revision retains 8.8 and 7.5. The system does not average or overwrite those assessments.

A declared CWE mapping without a valid `cweId` is quarantined. Valid CVE→CWE graph edges are emitted only from the explicit normalized `problemTypes.cweId` field with source qualifier and JSON-pointer support.

CVE update tests retain both immutable source revisions. Current exact lookup selects the later eligible revision; historical-public exact/lexical queries select the earlier revision at the earlier cutoff. After tombstone admission, the current overlay hides both from the already-published snapshot, while old immutable bytes remain addressable for audit. A rebuilt empty projection can then be coherently published.

### CISA KEV

The KEV adapter preserves CVE ID, date added, due date, known-ransomware-use field, action/description and catalog-version context. KEV membership remains a separate structured eligibility fact rather than modifying CVSS or canonical CVE truth.

When a later catalog is compared with a known previous CVE-ID set, missing entries emit explicit source deletions and enter the revocation lifecycle. The fixture validates that a removed entry is immediately tombstoned.

## Projection behavior

Core source outputs compose with the existing runtime:
- CVE and ATT&CK canonical objects project to exact evidence where appropriate;
- narrative fields project to independent lexical documents and are compatible with the generic dense pipeline when a validated embedding runtime is available;
- CVSS and KEV fields project to DuckDB structured schemas;
- CVE→CWE and explicit ATT&CK relationships project to sourced graph assertions;
- arbitrary CAPEC/ATT&CK links are not invented from similarity.

Post-deletion empty lexical generations are valid when the analyzer identity is pinned in the ProjectionBuildRequest. Both SQLite FTS5 and the MySQL FULLTEXT adapter now support that lifecycle case.

## Source metadata and coverage matrix

SourceManifest now carries source URI, source terms/license identifier and notice, connector fingerprint, parser/normalizer fingerprint, availability basis, update strategy, deletion strategy, retention class, and supported projections.

ATT&CK, CVE List, and CISA KEV are marked `fixture_validated`, not `live_validated`.

The coverage registry explicitly marks NVD, GHSA, CWE, CAPEC, D3FEND, ATLAS, CAR, Attack Flow, MISP, report/TRAM/sighting families, Sigma, Atomic Red Team, CVEfixes, MegaVul, PoC metadata, and SOC corpora as deferred with a concrete reason. No generic parser is used to imply unsupported coverage.

`scripts/cyber_sources.py` provides offline-first coverage, ingest, update-fixture, delete, and rebuild commands. `CORE_CYBER_BENCHMARK` defines exact-CVE, narrative passage, structured severity, KEV, and graph-mapping cases with source constraints.

## Validation actually executed

GitHub Actions run `35843384373`, job `107123568293`, Python 3.13.15:

- cumulative Phase 01–11 deterministic unittest suite: **114/114 passed in 4.884 s**
- Phase 11 core cyber source gate: **7/7 passed in 0.387 s**
- affected legacy API/runtime regression: **8/8 passed**
- cumulative validation registry: expected overall `fail` because external required gates remain blocked; `phase11-core-cyber-source-fixtures` is `pass`.

Phase 11 verifies:
- ATT&CK, CVE, and KEV real-format fictitious fixtures normalize with pinned source/parser/license metadata;
- coverage status is honest and benchmark cases cover exact, passage, structured, and graph evidence;
- invalid STIX and malformed CWE mapping evidence quarantine rather than project;
- CVE updates preserve two immutable revisions and historical/current retrieval selects the correct version;
- source tombstones block old published exact/lexical snapshots immediately and rebuild cleanly;
- ATT&CK revoked updates tombstone preserved revisions;
- KEV catalog removal emits a tombstone;
- CVSS source disagreements, scheme, units, source container, and historical versioning remain exact;
- KEV eligibility remains a typed structured fact;
- CVE→CWE graph joins exist only for explicit source-backed mappings and remain ontology-mapping semantics.

## Explicit blocked gate

`phase11-live-core-source-lifecycle` is blocked. CI did not fetch live ATT&CK/CVE/KEV upstream data or execute real network update/delete/reconciliation. Real-format offline fixture validation proves adapter/lifecycle mechanics, not current upstream availability, throughput, rate limits, or live source completeness.

NVD/GHSA/CWE/CAPEC and the extended source set are also not claimed implemented by this phase; their coverage entries remain deferred.

## Migration/rollback

No production source corpus was downloaded or replaced. The new source adapters are additive and write through the existing immutable object/canonical metadata/outbox/revocation contracts. Rollback is commit reversal and snapshot rollback; preserved old revisions are intentionally not deleted by ordinary source updates/tombstones.
