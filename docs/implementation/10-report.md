# Phase 10 implementation report — source-backed temporal graph assertion retrieval

Status: **implementation/own deterministic gate passed; cumulative acceptance blocked by real Neo4j restart/lifecycle and inherited external gates**

## Lineage and fingerprints

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/09-report.md`
- Validated Phase 10/11 code checkpoint: `d3395d26d9df72c60cea57e9d593b2b4901e68bc`
- Graph models: `59019cfd3e05ef615702625387f37d62420ecae8`
- Entity resolution: `a5c1eaf2a6dbde2fb2f52df068bf0849fd18dc97`
- Reference GraphPort: `b66bab8b9d25bd81a3270dc1653085d533d4e37e`
- Neo4j fixed-query adapter: `79ecf00a20db8697508242922ead3aa162c521f5`
- Assertion/entity contracts: `a12289a33dabccc3d1cb5178b804313ff7f97d87`
- Typed candidate contract: `c2eb3a1cd4efbd79611fa83b8bef4485d223b9b6`
- Phase 10 test blob: `6676ffb363414b0e3b97423372b84af4032a73c4`
- Opt-in real Neo4j test blob: `a7f74fc2868747d687e052b73d3ebd038517cf7f`

## Implemented

### Canonical typed entities and sourced assertions

Graph entity identity no longer depends on a display name. `make_entity_uid` derives deterministic identity from namespace, entity type, and canonical identifier. `EntityRef` can bind that UID, and `SourceAssertion` now carries source ID, policy labels, availability, valid interval, system-manifest identity, qualifiers, epistemic metadata, and one or more supporting provenance locators.

`EntityResolutionJournal` separates confirmed identity, possible identity, and alias relations. Every resolution decision has source support and event history. Confirmed closure only follows active `confirmed_same_entity` decisions; possible links never become transitive fact. Confirmed merges across different entity types are rejected. Split/restore operations preserve reversible audit history.

### Traversal templates and fail-closed eligibility

`TraversalTemplate` defines allowed predicates, subject/object types, and direction. `GraphRequest` is bounded by default/validation to at most two hops, eight seeds, degree 20, 100 returned paths, an examined-edge cap, one deadline, and cancellation.

The reference GraphPort selects the graph generation from the pinned snapshot and applies current revocations, entity policy, assertion policy, requested source scope, temporal eligibility, system-replay eligibility, and support resolvability before building adjacency. Private bridge nodes are therefore absent before public degree/edge budgets are counted.

A path also requires compatible assertion valid-time intervals. Cycles are rejected by node-chain membership. Truncation is explicit on GraphPathHit/ChannelResult when degree, path, examined-edge, or hop limits prevent full traversal.

### Typed graph output and query-DAG integration

GraphPathHit carries:
- node UIDs;
- assertion UIDs and human-readable assertions;
- relation types;
- source-backed provenances/revision UIDs;
- epistemic labels;
- source IDs and policy metadata;
- semantic label;
- truncation state.

Grouped fusion retains graph paths outside passage RRF. The query executor passes the plan's temporal request to the new GraphPort while preserving compatibility with older graph test doubles. Context packing treats paths as typed evidence obligations. The advanced evidence API now serializes graph paths and final-response admission rechecks current scope and current revocations.

Ontology chains use `ontology_mapping_path`; tests explicitly prevent representing CVE→CWE→CAPEC→ATT&CK mapping as observed technique use. The system keeps the two-hop traversal limit: the three-edge chain is resolved through bounded traversals rather than an unbounded single expansion.

### Neo4j adapter

`Neo4jGraphProjectionAdapter` installs uniqueness constraints for graph entity/assertion/generation IDs and uses fixed parameterized MERGE statements to project immutable graph generations. It does not expose arbitrary Cypher to the planner/model/client. Fixture driver tests verify repeatable constraint/upsert behavior and absence of a dynamic CALL surface.

An opt-in real-driver test exists for actual Neo4j constraint/reconnect validation. CI did not have a reachable Neo4j service with server restart control, so restart persistence is not claimed.

## Validation actually executed

GitHub Actions run `35843384373`, job `107123568293`, Python 3.13.15:

- cumulative Phase 01–11 deterministic unittest suite: **114/114 passed in 4.884 s**
- Phase 10 deterministic graph gate: **9/9 passed in 0.097 s**
- affected legacy API/runtime regression: **8/8 passed**
- cumulative validation registry: expected overall `fail` because required external gates remain blocked; `phase10-graph-assertion-invariants` is `pass`.

Phase 10 specifically verifies:
- same-name unrelated entities remain distinct;
- possible identity does not become confirmed transitive closure;
- confirmed links support reversible split/restore and reject cross-type merge;
- every returned edge has resolvable support;
- missing support cannot expose an edge;
- historical non-overlapping assertion validity cannot form a path;
- private intermediate nodes are removed before degree/edge budgets and cannot affect public truncation;
- high-degree traversal is deterministically capped with visible truncation;
- the longer CVE→CWE→CAPEC→ATT&CK chain respects the two-hop cap and is labeled ontology mapping;
- graph paths execute through query DAG → grouped fusion → context packer as typed evidence outside passage RRF;
- current assertion revocation immediately hides a path from a previously published immutable graph snapshot;
- Neo4j projection queries use fixed MERGE/constraint operations and deterministic IDs.

## Explicit blocked gate

`phase10-real-neo4j-restart-lifecycle` is blocked. The repository contains an opt-in real Neo4j driver/reconnect test, but CI did not execute a service restart/recovery sequence. This phase therefore does not claim real Neo4j restart persistence or production graph-service readiness.

## Migration/rollback

The legacy graph store is not rewritten in place. New graph generations are derived projections selected by the shared snapshot catalog. The feature remains additive behind the existing advanced retrieval composition; rollback is snapshot/commit reversal and cleanup of unpublished graph generations.
