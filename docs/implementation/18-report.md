# Phase 18 implementation report — hardened external search and request-local live evidence

Status: **own deterministic gate passed; cumulative acceptance remains blocked by missing Phase 14 and inherited/external gates**

## Lineage and validation

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/17-report.md`
- Validated code checkpoint: `9d916727eeec3e284fb49182965bca96b82538c6`
- Actions run/job: `36108375446 / 107986009014`
- Python: 3.13.15
- Cumulative deterministic suite: **157/157 passed in 11.253 s**
- Phase 18 gate: **9/9 passed in 0.016 s**
- Affected legacy regressions: **8/8 passed**
- Registry audit through Phase 18 succeeded in remaining fail-closed.

Key fingerprints are recorded in `validation/reports/phase-18.json`. No live corpus or production index was mutated.

## Implemented

### Discovery providers remain discovery-only

Added backend-neutral `SearchProvider` contracts plus:
- a configured SearXNG adapter;
- a wrapper for the repository's existing Tavily/WebSearcher integration.

Provider snippets are typed `DiscoveryItem` metadata and are explicitly non-citable. Only separately fetched source bytes can become captured evidence.

Every provider request calls the new network-policy authorization surface before query text reaches the provider. Non-public terms additionally require an explicit minimizer. Public-only/default runtime policy grants no remote network destinations.

### Hardened FetchPort

`HardenedFetchPort` validates before the initial connection and every redirect:
- allowed HTTP/HTTPS schemes and ports;
- no URL userinfo;
- all resolved IPv4/IPv6 destinations;
- loopback, link-local, private/internal, multicast, unspecified, reserved, and metadata-address classes are denied by default;
- the socket is pinned to an already validated IP, so DNS is not re-resolved at connect time;
- the transport-reported peer must match the authorized resolution set;
- redirects are re-resolved and re-authorized.

The direct pinned transport ignores environment proxy variables. Passing a proxy URL to this adapter is rejected because proxy egress requires a separately attested transport rather than silently changing the actual destination.

### Resource bounds and hostile parsing

The fetcher bounds redirects, wire bytes, decompressed bytes, output text, content types, connection time, and parser time. Gzip/deflate expansion is bounded. Archive parsing is not enabled.

HTML/JSON/XML/plain-text source parsing runs in a spawned subprocess with timeout and best-effort CPU/address-space limits. Captured bytes receive a content digest, immutable capture/revision identity, provenance, fetch/availability times, and `untrusted_content=True`. Retrieved instructions never gain tool authority.

### Request-local overlay and persistence boundary

`LiveEvidenceOverlay` is separate from the pinned base response and carries its own overlay identity. The disabled path returns without touching provider/fetch components, making offline behavior network-independent by construction.

Provider/fetch failures leave the already-valid local/base evidence available.

There is no query-handler persistence method. `CapturedOverlayConnector` is an explicit bridge that converts selected captures into ordinary immutable `SourceRecord` objects; persistence/publication then follows the existing ingestion/snapshot lifecycle.

## Acceptance evidence

Passed fixtures cover:
- denied private query never reaching the provider spy;
- search snippets never becoming citations;
- redirect to metadata/link-local destination;
- IPv6 loopback;
- simulated peer/DNS rebinding mismatch;
- wire-size, decompression, and invalid-type rejection;
- hostile prompt-like document text retained only as untrusted evidence;
- offline mode that raises if any provider/fetch call is attempted;
- provider outage with local retrieval preserved;
- explicit ingestion bridge for persistence.

Live SearXNG/Tavily and production proxy/egress validation remain **blocked** because no approved live endpoint/credentials or separately attested production proxy transport were supplied. The deterministic mock/transport tests are not mislabeled as live-network validation.

## Migration and rollback

The web overlay is **disabled by default** behind `CTI_RAG_WEB_OVERLAY_ENABLED`; the existing advanced evidence endpoint remains offline unless a future composition explicitly binds the overlay. Public-only policy has no network destinations by default. Rollback removes the optional web package/network policy destinations without modifying pinned corpus snapshots or captured source history already admitted through ordinary ingestion.

## Handoff

The next independent prompt can proceed. Cumulative promotion remains blocked by Phase 14 and inherited external-real-system gates.
