# Phase 1 implementation report — immutable evidence and citation contracts

Status: **contract implementation passed; cumulative acceptance remains blocked by required Phase 0 runtime gates**

## Implemented

A new side-effect-free `cti_rag.contracts` package defines immutable source objects/revisions, retrieval observations, normalized artifacts, passages, indexed representations, source assertions, provenance/lineage, temporal metadata, policy labels, query/snapshot contracts, and discriminated candidate payloads.

Identity uses versioned canonical JSON plus namespaced SHA-256 hashes for `object_uid`, `revision_uid`, `artifact_uid`, `passage_uid`, `representation_uid`, and `assertion_uid`. Canonicalization normalizes Unicode to NFC, sorts object keys, preserves nulls, requires timezone-aware datetimes, and rejects non-finite numbers. Parser, normalizer, chunker, model, tokenizer, analyzer, and prefix fingerprints participate at the relevant derived layers.

Typed locators cover character spans, JSON Pointers, pages, table keys, TEI paths, and canonical passages. Historical uncertain ranges are distinct from precise instants and availability basis is explicit.

Typed retrieval envelopes are `PassageHit`, `EntityHit`, `GraphPathHit`, and `StructuredResult`. Graph and structured payloads remain typed instead of requiring text flattening. Retrieval-attempt IDs and raw score metadata are separate from citable identity. Candidate merging uses citable typed identity, never text alone, so editions/revisions are not collapsed.

Repeated downloads append retrieval observations without manufacturing a new revision. Access/processing labels are defined in contracts; enforcement is intentionally deferred.

The contract package has no Milvus, Neo4j, SQLAlchemy, FastAPI, model-SDK, or web-client dependency. Legacy runtime imports are unchanged, and no API/composition root activates the new retrieval path.

## Tests

Executed:

```text
python -m unittest tests.contracts_phase1_test tests.validation_runner_test -v
```

Result: **17 tests passed** (12 Phase 1 contract invariants + 5 validation-runner invariants).

Covered acceptance behaviors include stable identity, source-revision preservation, delimiter ambiguity resistance, Unicode/map canonicalization, observation-vs-revision separation, provenance preservation for identical text, fingerprint-sensitive derived IDs, malformed timestamp/locator rejection, unknown discriminator rejection, and fail-closed cumulative gate status.

## Remaining blocker and handoff

`scripts/validate_phases.py --through-phase 1` intentionally exits unsuccessfully while the two required Phase 0 legacy runtime gates remain blocked. Independent Phase 2 canonical-ingestion implementation can proceed from these contracts, but dependent runtime activation/promotion must not be claimed accepted until those inherited gates execute successfully.

Rollback is a revert of these additive files; no live storage/index migration occurred.
