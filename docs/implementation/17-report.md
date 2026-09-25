# Phase 17 implementation report — claim grounding, abstention, and bounded contradiction retrieval

Status: **own deterministic gate passed; cumulative acceptance remains blocked by missing Phase 14 and inherited/external gates**

## Lineage and validation

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Parent report: `docs/implementation/16-report.md`
- Validated code checkpoint: `9d916727eeec3e284fb49182965bca96b82538c6`
- Actions run/job: `36108375446 / 107986009014`
- Python: 3.13.15
- Cumulative deterministic suite: **157/157 passed in 11.253 s**
- Phase 17 gate: **8/8 passed in 0.015 s**
- Affected legacy regressions: **8/8 passed**
- Phase 14 remains a required missing prerequisite; the registry remains fail-closed.

Key fingerprints are recorded in `validation/reports/phase-17.json`. No corpus was changed. The generator fixture fingerprint is `generator-fixture/1`; no evaluated production semantic judge was supplied, so its evaluation state remains **unknown/blocked**, not passed.

## Implemented

### Claim-to-span grounding

Added typed claim/citation/span contracts and four outcomes: `supported`, `contradicted`, `mixed`, and `insufficient`. A citation pointer is not support by itself. Citation targets must resolve to a packed passage whose canonical citation verification already passed.

Deterministic validators independently check:
- exact quotation text;
- identifiers;
- date strings;
- typed numeric values and units.

Semantic entailment is optional and isolated behind `ModelPort`. Judge failure/evaluation status is recorded separately from exact validation.

### Contradiction qualification and source independence

Numeric disagreement is only treated as contradiction when the relevant entity, valid time, edition, source revision, and unit are compatible. Unit/time/edition/revision mismatches are retained as non-applicable evidence rather than mislabeled direct contradictions.

Evidence metadata now supports `conflict_group`, `entity_key`, `valid_time`, and `edition_key`. The context packer reserves distinct source origins for declared conflict groups before ordinary redundancy pruning. Multiple syndicated copies from one `origin_group` count as one origin for confirmation reporting.

### One bounded follow-up

`BoundedFollowUpSearch` permits at most one extra lexical/dense evidence search. It:
- rejects recursive proposals;
- reuses the immutable original effective scope, temporal request, and pinned snapshot;
- respects the original plan's backend-call budget plus a separate one-call cap;
- bounds candidates and returned token budget;
- never writes model hypotheses or follow-up results into the evidence store.

### Optional answer generation

`GroundedAnswerService` re-authorizes evidence for the generation destination, invokes the configured `ModelPort`, then re-runs grounding over generated claims. Unsupported claims are omitted from the final answer and returned in `unresolved`. Generation and semantic-judge fingerprints/evaluation states are returned explicitly.

## Acceptance evidence

Passed fixtures demonstrate fabricated quotes, altered numbers, invalid/non-supporting citations, false contradiction avoidance across unit/time/edition/revision differences, single-hop fencing, source-origin grouping, conflicting-evidence preservation, semantic-judge error isolation, useful answerable coverage, and abstention on unsupported claims.

The evaluated-production-semantic-judge gate remains **blocked** because no pinned judge/model with measured entailment error characteristics was available. Fake/model-spy success is not reported as semantic quality evidence.

## Migration and rollback

The grounding service is additive and not enabled by default. Existing evidence-only retrieval contracts remain compatible. New `EvidencePassage` metadata fields are optional. Rollback can remove the grounding package and optional metadata/packer reservation pass without rewriting immutable evidence revisions or snapshots.

## Handoff

Independent Phase 18 work can proceed and has been implemented. Cumulative promotion still cannot pass until Phase 14 and inherited external gates are satisfied.
