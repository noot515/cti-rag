# Phase 19 implementation report — canonical RuntimePolicy policy-port adapter

Status: **adapter conformance gate passed; canonical package/live broker validation remains blocked; cumulative acceptance remains blocked**

## Lineage and validation

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/18-report.md`
- Validated code checkpoint: `10f59b356be07d85d88f605472a4a6e2e9399c9f`
- Actions run/job: `36112418435 / 107998666984`
- Python: 3.13.15
- Cumulative deterministic suite: **174/174 passed in 10.242 s**
- Phase 19 recorded-wire/local-server conformance: **8/8 passed in 0.019 s**
- Affected legacy regressions: **8/8 passed**
- Cumulative registry audit through Phase 20: succeeded while intentionally remaining overall fail-closed.

## Canonical contract pinned

The adapter records the inspected canonical RuntimePolicy identity in `cti_rag/infrastructure/runtimepolicy_pin.json`:

- repository: `noot515/existential`
- source commit: `a8d809c07c808dd0519e0cef4dd923d11b996799`
- inspected main commit: `8fa9a456b1e611a77f7348bf16f018e259c6e188`
- runtime: **1.4.0**
- wire contract: **1.0.0**
- broker protocol: **3**

The relevant runtime package blobs were byte-identical between the pinned source commit and the inspected main commit. The adapter imports the canonical package lazily and checks its exported contract identity plus the broker compatibility handshake before authorization.

## Implemented

### External PolicyPort adapter

`RuntimePolicyProvider` implements the existing `PolicyPort` without moving policy logic into core contracts. It:

- binds authenticated principal, tenant, purpose, domains, source IDs, access labels, processing classes, and destination into the exact action payload;
- uses canonical `Action`, `Assessment`, `RuntimePolicy`, `DecisionRecord`, and `AuthorityClient` types when the pinned package is installed;
- registers the exact request with the broker on host `research`;
- rejects malformed, expired, version-mismatched, or non-`act` assessments;
- audits the exact decision and calls broker `check()` before accepting the admission;
- preserves the assessment revision and rechecks the same exact admission before response exposure;
- rejects revision drift or expiry instead of silently obtaining a broader replacement scope;
- separately assesses model and network destinations;
- never falls back from unavailable external/private authorization to the public-only local provider.

The existing local public-only policy remains a separate explicit mode.

### Policy contract extension

`ClientScopeRequest` now carries optional processing classes and a purpose. `EffectiveScope` records provider/revision/expiry/assessment/action-binding metadata. Existing positional callers remain compatible. `AdvancedRetrievalService` uses `revalidate_for_response` when a provider implements it, so an external provider can revalidate the original admission rather than minting a fresh unrelated scope.

## Acceptance evidence

The Phase 19 fixture uses a framed Unix-domain contract server and recorded canonical wire shapes. It validates:

- exact request fields and no scope expansion;
- response revalidation without a second assessment;
- state-revision change rejection;
- expired and malformed assessment rejection;
- wrong model destination denial;
- local-only remote-dispatch denial;
- exact network endpoint binding;
- invalid compatibility handshake rejection;
- external-service outage without private/local fallback;
- local public mode remaining explicit and separate.

These tests validate the adapter boundary and wire behavior. They **do not** substitute a copied/reimplemented kernel for the canonical package.

## Required blocked evidence

Two Phase 19 gates remain blocked:

1. `phase19-canonical-runtime-client-package` — GitHub Actions for this repository cannot anonymously clone the pinned private `noot515/existential` source commit. No RuntimePolicy source/kernel was vendored into cti-rag to manufacture a pass. Clearing this gate requires an authenticated exact package/artifact or CI read credential.
2. `phase19-live-runtimepolicy-broker` — no deployment broker socket, peer identity, operator-reviewed live evidence/grants, or production-readiness attestation was supplied.

No live affirmative grant was fabricated from test fixtures.

## Migration and rollback

The external provider is optional. Minimal/public deployments can continue using `PublicOnlyLocalPolicy`. Removing the adapter and its integration requirements does not rewrite evidence, snapshots, or local policy state. The advanced retrieval response path remains disabled by default as before.

## Handoff

Phase 20 is independently implemented and validated below. Cumulative promotion remains blocked by the missing Phase 14 prerequisite and inherited/live-system gates.
