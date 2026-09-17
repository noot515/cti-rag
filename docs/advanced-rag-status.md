# Advanced RAG V3 implementation status

Updated: 2026-09-17. Prompt 13 documented head / Prompt 14 predecessor: `73a0429dc7de58714148197172f9fffb68baf052`. Current stacked branch: `feat/advanced-14-evidence-packing`. Legacy retriever/model/reranker/API behavior remains available and unchanged.

## Prompt 12/13 inherited boundary

Prompt 12 provides request-scoped scope/snapshot resolution, bounded exact/lexical/dense execution, seed-gated graph retrieval, deterministic equal-weight RRF and a pre-rerank limit of 60. Prompt 13 provides the single optional final reranking stage with complete output validation, final evidence reauthorization before provider egress, exact-lookup priority preservation and deterministic fallback to the full pre-rerank order.

The final Prompt 13 descendant compatibility gates were `15 passed` for Prompt 12, `17 passed` for Prompt 13 and `32 passed` combined. The strict target-environment predecessor chain remains `scripts/validate_advanced_04_13.py` and is still `not_run` here because the implementation sandbox is Python 3.13.5 with no Python 3.11 or Docker.

## Prompt 14 - token-budgeted context, path integrity and citations

Prompt 14 adds the terminal evidence egress stage after final candidate ordering:

- `CitationRef` carries stable evidence identity, object/assertion revision identity, domain/scope/snapshot, optional source field/offset coordinates, source URI and source instance. `CTI-001` style labels are generated only for actually emitted evidence and remain response-local rather than global evidence identity;
- `PackResult` records answer context, local citation map, packed candidate/evidence/revision identities, omissions with reasons, tokenizer fingerprint, exact token count/budget, packing mode, citation validity and an explicit `claim_support=not_assessed` distinction;
- context budget is `min(8000, model_window - system - history - query - output_reserve - safety_margin)`. A nonpositive result rejects packing;
- the injected tokenizer counts the fully rendered response including citation labels, headers and separators. `FixtureGeneratorTokenizer` is explicitly mechanics-only and does not claim production generator equivalence;
- at most 15 blocks are emitted. Ranked first-pass soft per-object/source caps may defer evidence, but the hard block and token limits are never relaxed;
- each candidate block is indivisible. Oversized blocks are omitted with `token-budget`, never clipped into a stronger statement;
- paths require all node/object, assertion and support citation classes before they may render. `CatalogEvidenceResolver` checks exact pinned generation membership and live withdrawal state for every node/assertion/support component and authorizes the complete set;
- mapping/reference/assertion semantics and assertion kind remain explicit in path rendering; contradictory independent assertions are retained rather than merged into fabricated consensus;
- object/chunk source URI and source offsets are read only from the local catalog metadata. Packing never fetches a source URL or calls an LLM/tool;
- evidence text is rendered under an explicit untrusted-content header. Instructions found in evidence do not alter policy, execute tools or trigger URL retrieval;
- duplicate evidence is suppressed by stable evidence/revision identity without suppressing distinct contradictory evidence;
- after provisional packing, every accepted block is resolved and authorized again. A last-moment withdrawal, policy denial or changed authoritative block causes deterministic suppression/rebuild before response return;
- basic and structured formatting modes share the same candidate and token-budget contract for later comparison.

### Prompt 14 focused validation

Available implementation sandbox: Python 3.13.5 compatibility workspace; repository target: Python 3.11.

```text
PYTHONPATH=. python -m pytest \
  tests/unit/retrieval/test_context_packer.py \
  tests/unit/retrieval/test_citations.py \
  tests/e2e/test_evidence_egress.py -q
10 passed
```

Combined Prompt 12/13/14 compatibility mechanics in the local workspace:

```text
42 passed
```

The focused tests cover exact budget boundaries, multibyte emitted offsets, oversized indivisible paths, mandatory path support evidence, citation resolution, duplicate chunks, contradictory sources, malicious instruction text and withdrawal after reranking before response emission.

## Unresolved target-environment / operational gates

- exact chained Prompt 04+ correctness on a complete Python 3.11 checkout;
- full repository collection at the final later-stack head;
- real Milvus and Neo4j service roundtrip/isolation inherited from earlier phases;
- authenticated restricted-evidence service configuration;
- real reranker/model compatibility and retrieval-quality promotion gates.

No unavailable service/model or target-environment gate is inferred from fixture/fake-provider mechanics.

## Handoff

Prompt 14 offline mechanics are implemented on top of Prompt 13. Prompt 15 may start from the final Prompt 14 documented SHA, but advanced API identity/corpus grants must remain server-owned and must not infer authorization from legacy request-body ownership fields.
