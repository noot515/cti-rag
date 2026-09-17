# Advanced RAG V3 implementation status

Updated: 2026-09-17. Prompt 14 documented head / Prompt 15 predecessor: `65701c1885ead1901e0f84c95227a1ced25190e2`. Current stacked branch: `feat/advanced-15-trusted-principal-and-corpus-access`. Legacy retriever/data/session routes remain available; advanced authorization does not infer ownership from legacy request-body fields.

## Prompt 14 - evidence packing and citations

Prompt 14 adds terminal token-budgeted evidence packing after final candidate ordering. `CitationRef` preserves stable evidence/revision/scope/snapshot/source coordinates while response-local labels such as `CTI-001` are assigned only to actually emitted evidence. Context budgeting counts rendered labels/headers/separators with an injected tokenizer, paths are indivisible node/assertion/support bundles, contradictory evidence is retained, evidence text is quoted as untrusted content, and accepted blocks are resolved/authorized again before return so a last-moment withdrawal causes suppression/rebuild.

Focused local compatibility gate:

```text
python -m pytest tests/unit/retrieval/test_context_packer.py tests/unit/retrieval/test_citations.py tests/e2e/test_evidence_egress.py -q
10 passed
```

Combined Prompt 12/13/14 compatibility mechanics: `42 passed`.

## Prompt 15 - trusted API identity and server-owned corpus grants

Prompt 15 creates a new advanced authorization boundary rather than trusting legacy knowledge-database ownership:

- `TrustedPrincipal` now requires an explicit ID namespace. API authentication constructs `principal_namespace="user.id"` from canonical authenticated `User.id`; the inspected legacy/login `User.user_id` is not used as advanced identity;
- `ResolvedScope` can carry the trusted principal namespace and server-owned `active_catalog_id` while remaining backward-compatible with earlier scope constructors;
- `CorpusAccessStore` is an advanced SQLite authority store with WAL/foreign keys/full synchronous writes, restrictive local permissions where supported, explicit corpora and grant tables, no result cache and no import of the legacy MySQL manager;
- corpus registration owns `domain`, `scope_id`, active catalog, policy version, source allowlist, destinations and namespaced grants. Unknown, disabled, ownerless and unauthorized corpora all fail closed; external unknown/unauthorized behavior is intentionally indistinguishable;
- `CorpusGrantPolicy` revalidates the current grant and corpus version on every evidence authorization. Grant revocation, catalog change, policy-version change or source/destination mismatch therefore invalidates a previously resolved/pinned scope instead of being cached permissively;
- advanced evidence authorization remains fail closed for unresolved/granular markings and for restricted dissemination until an explicit production marking policy exists. Public fixture behavior remains separately controlled by `PublicFixturePolicy`;
- `rag/api/advanced_dependencies.py` converts only canonical authenticated users to trusted principals, maps identity failure to 401, unknown/unauthorized corpus to 403, and grant-store outage to 503. User-controlled body fields such as `user_id`, principal or policy names are not inputs to this resolution;
- construction of the protected FastAPI dependency is the advanced startup boundary: `AuthUtils.configure_advanced_signing()` requires an explicitly configured non-default signing authority before the legacy DB-backed user lookup is imported/used;
- `AuthUtils` now catches the actual python-jose `ExpiredSignatureError`/`JWTError` classes rather than PyJWT-style attributes. The advanced API dependency profile pins FastAPI, python-jose and passlib separately in `requirements-advanced-api.txt`;
- token issuer/verifier can share the validated `JwtSigningConfig`. The key itself is not logged. `docs/advanced-auth-transition.md` documents the operator transition: changing the authority invalidates older tokens and requires re-authentication rather than a permissive dual-key/fallback mode;
- `python -m packages.evidence.cli register-corpus --config CONFIG --grant-file FILE` is the only new corpus-registration surface. It requires a trusted-local administrator capability and validates an administrator-authored manifest; nothing is added to the unprotected legacy data route.

### Prompt 15 validation status

Locally feasible dependency-free core on Python 3.13.5:

```text
python -m pytest <dependency-free identity core> tests/unit/evidence/test_corpus_access.py -q
7 passed
```

Combined locally feasible Prompt 12-15 mechanics/core:

```text
49 passed
```

The complete requested Prompt 15 command is intentionally `not_run` in this sandbox because the pinned JOSE dependency cannot be installed: package-network DNS is unavailable. The branch nevertheless contains the full target tests for valid, expired, malformed and wrong-signature tokens, missing signing authority, canonical ID/login-ID collision, forged body ownership, ownerless corpus, two tenants, mid-query grant revocation, policy-store failure and zero backend/provider calls on denied access.

The target command remains:

```text
python -m pytest tests/unit/api/test_advanced_identity.py tests/unit/evidence/test_corpus_access.py -q
```

## Chained validation

`scripts/validate_advanced_04_15.py` is the strict Python 3.11 handoff. It verifies the Prompt 14 ancestor, runs `scripts/validate_advanced_04_13.py`, then Prompt 14, Prompt 15, fresh import safety, compileall, `git diff --check`, and a final full-repository collection at the Prompt 15 head.

The exact chain remains `not_run` here because:

```text
Python 3.13.5
Python 3.11 unavailable
Docker unavailable
package-network DNS unavailable
```

No prior compatibility result is relabeled as that exit gate.

## Remaining operational/quality gates

- `python scripts/validate_advanced_04_15.py` on a complete Python 3.11 checkout with `requirements-advanced-dev.txt` installed;
- final full repository collection on the Prompt 15 head;
- real Milvus/Neo4j roundtrip and legacy-isolation gates inherited from earlier phases;
- deployment wiring of protected advanced routes using `make_advanced_access_dependency`;
- production restricted-marking policy beyond fail-closed behavior;
- real reranker/model compatibility and retrieval-quality/promotion gates.

## Handoff

Prompt 15 correctness mechanics are implemented on top of Prompt 14. Later protected retrieval/API phases may consume `AdvancedAccessContext`, `TrustedPrincipal`, `CorpusAccessStore` and `CorpusGrantPolicy`, but must not accept body principals or legacy database ownership as authorization.
