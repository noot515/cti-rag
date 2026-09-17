# Current state and sequencing handoff

Prompt 15 begins from Prompt 14 documented head `65701c1885ead1901e0f84c95227a1ced25190e2` on `feat/advanced-14-evidence-packing` and is stacked on `feat/advanced-15-trusted-principal-and-corpus-access`.

Reconciliation notes:

1. Prompt 14 remains the final evidence-packing/citation boundary. Prompt 15 changes who may resolve an advanced corpus; it does not alter retrieval ranking, reranking or packing semantics.
2. The inspected authentication path already signs token `sub` with canonical `User.id`. The separate legacy/login `User.user_id` is therefore never accepted as advanced identity. `TrustedPrincipal` adds the explicit namespace `user.id`.
3. The inspected `User` model has `is_active`; advanced identity rejects inactive users. No nonexistent deleted/disabled column is invented.
4. Legacy `KnowledgeDatabase.user_id` is caller-populated through the legacy data route and is never imported into the advanced grant store. Request-body `user_id`, principal or policy fields cannot affect advanced authorization.
5. `CorpusAccessStore` is a separate SQLite authority with server-owned corpus key, domain, scope, active catalog, policy version, source allowlist, destinations and namespaced grants. It uses no result cache and does not import the legacy DB manager.
6. Unknown, disabled, ownerless and unauthorized corpus resolution fail closed. The advanced API maps unknown and unauthorized corpus to the same 403 response so existence is not disclosed through authorization behavior.
7. Access-store errors raise `CorpusAccessUnavailable`; advanced HTTP mapping is 503 and there is no permissive fallback.
8. `CorpusGrantPolicy` calls `assert_scope_current` during evidence authorization. Revoked grants, active-catalog changes, policy-version changes or changed allowlists/destinations invalidate a previously resolved scope during the same pinned query.
9. Restricted dissemination remains fail closed unless an explicit production marking policy is added. `PublicFixturePolicy` remains the only narrow synthetic/public fixture exception and still requires its explicit source allowlist.
10. `AuthUtils` now catches python-jose `ExpiredSignatureError` / `JWTError` rather than PyJWT-style attributes. `requirements-advanced-api.txt` pins the advanced API identity dependencies independently of the legacy API requirement set.
11. Constructing `make_advanced_access_dependency` is the protected advanced startup boundary: `AuthUtils.configure_advanced_signing()` requires a non-default operator-managed `JWT_SECRET_KEY` and activates one issuer/verifier configuration before the DB-backed authenticated-user dependency is imported.
12. A signing-key transition invalidates older tokens and requires reauthentication; `docs/advanced-auth-transition.md` explicitly rejects a temporary permissive fallback/dual-key mode. Environment examples show names/placeholders only.
13. Corpus registration is `python -m packages.evidence.cli register-corpus --config CONFIG --grant-file FILE`. It requires a trusted-local principal with `corpus:register` capability and validates a local administrator-authored manifest; no public legacy route is widened.
14. Local Python 3.13.5 dependency-free access/identity core passed `7` tests; combined locally feasible Prompt 12-15 mechanics/core passed `49`. Actual JOSE token tests remain `not_run` locally because package-network DNS is unavailable.
15. `scripts/validate_advanced_04_15.py` is the new strict Python 3.11 correctness handoff. It invokes the full Prompt 04-13 chain, Prompt 14, Prompt 15, import safety, compile/whitespace and a final full collection.
16. Exact Python 3.11, pinned JOSE token execution, full collection, live Milvus/Neo4j isolation, production restricted-marking policy and quality/promotion gates remain independent unresolved gates; offline mechanics do not authorize deployment.
