# Current state and sequencing handoff

Prompt 09 begins from Prompt 08 documented head `397f3ba49b94bc93a462b7e09c2f7d51f76bd4c5` on `feat/advanced-08-embedding-provider-contract` and is stacked on `feat/advanced-09-milvus-projection`.

Reconciliation notes:

1. Prompt 08 is the embedding/model identity authority. Prompt 09 does not infer dimensions or model identity from Milvus; the generation dense projection fingerprint must equal the selected provider fingerprint exactly.
2. Prompt 06 remains the publication authority. `MilvusProjection` is a projection writer that must verify its generation visibility before its receipt can participate in activation; Prompt 09 does not add a second active-generation pointer.
3. Full evidence, policy and provenance stay in the Prompt 05 SQLite catalog. Milvus stores only retrieval keys, generation/scope/model identity and the vector needed for dense retrieval.
4. Advanced collection identity is generation-scoped and namespaced. A different scope or generation gets a different collection name. Reingesting the same generation uses upsert and the same collection rather than delete/recreate.
5. Existing collection schema mismatch fails closed. The advanced client protocol and `Pymilvus23Adapter` intentionally expose no collection drop method, so this path cannot silently destroy an incompatible collection.
6. All VARCHAR limits are checked in UTF-8 bytes before collection creation/write side effects. `chunk_uid` is a manual string primary key; vector dimension comes only from the fingerprint-bound provider.
7. Evidence destination authorization occurs before document embedding. Query embedding requires an explicitly allowed resolved-scope destination before provider work.
8. Milvus search uses backend prefilters for domain, scope, generation and embedding fingerprint, but the catalog remains authoritative. Every backend result is rechecked against pinned snapshot membership plus current object revision, so stale backend rows are dropped.
9. Over-fetch is explicit and bounded; query statistics record backend limit/rows, accepted rows and truncation. Prompt 09 performs no BM25 and no reranking inside Milvus.
10. Service outages are explicit channel errors. There is no fallback to a legacy Milvus endpoint, another model, or another generation.
11. `Pymilvus23Adapter` is optional/lazy and checks the pinned client version before connection. The service matrix pairs Milvus 2.3.4 with PyMilvus 2.3.7; exact live compatibility remains a real-service gate.
12. `deploy/advanced-services.compose.yml` uses a separate Compose project, internal network, unique volumes and loopback host port 19531. etcd/MinIO are not host-published. MinIO credentials have mandatory environment placeholders and no committed defaults.
13. The default compatibility Compose stack does not establish authenticated Milvus users. Therefore it is suitable only for isolated synthetic/public compatibility testing; restricted-evidence service promotion is blocked until an authenticated advanced configuration is supplied and tested.
14. Real legacy isolation is not inferred from the namespacing design. `tests/integration/test_advanced_milvus.py` separately verifies that a configured legacy endpoint cannot see the advanced collection when both integration URIs are supplied.
15. Focused Prompt 08/09 sandbox validation passed (`24 passed`: 12 P08 + 12 P09 fake-client tests). Real integration collected as `2 skipped` because service URIs are absent. Docker is unavailable, so Compose parse/start is `not_run` in the implementation sandbox.
16. `scripts/validate_advanced_08_09.py` is the fail-fast Python 3.11 handoff. It verifies this branch descends from the documented Prompt 08 head, chains all 24 focused tests, compile validation and `git diff --check`, then validates Compose if Docker exists. Real service startup is opt-in and requires explicit integration URIs.
17. Exact Python 3.11/full-repository validation, real Milvus 2.3.4/PyMilvus 2.3.7 roundtrip, legacy-endpoint isolation, authenticated restricted-evidence service configuration, and retrieval-quality gates remain release blockers and must not be inferred from fake-client results.
