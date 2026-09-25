# RuntimePolicy adapter operator notes

The external policy mode uses the canonical `respectful-runtime` Unix broker client. It is optional; the default public-only provider remains `PublicOnlyLocalPolicy`.

Pinned integration identity is recorded in `cti_rag/infrastructure/runtimepolicy_pin.json`: source commit `a8d809c07c808dd0519e0cef4dd923d11b996799`, runtime 1.4.0, wire contract 1.0.0, broker protocol 3. The relevant package bytes are unchanged on inspected main commit `8fa9a456b1e611a77f7348bf16f018e259c6e188`.

Install the optional dependency from the pinned integration requirements, then configure. The pinned `noot515/existential` source is private in the current deployment: CI/hosts therefore need authenticated read access or an operator-built exact wheel for that commit. Do not vendor a substitute RuntimePolicy implementation into cti-rag to bypass package access.

- `RESPECTFUL_BROKER_SOCKET`: required broker Unix socket.
- `RESPECTFUL_BROKER_UID`: optional expected socket owner UID.
- `CTI_RAG_RUNTIMEPOLICY_TIMEOUT_SECONDS`: 0.1–30 seconds; default 5.
- `CTI_RAG_RUNTIMEPOLICY_DOMAINS`: local ceiling, default all five runtime domains.
- `CTI_RAG_RUNTIMEPOLICY_SOURCE_IDS`: optional source ceiling.
- `CTI_RAG_RUNTIMEPOLICY_ACCESS_LABELS`: default `public`.
- `CTI_RAG_RUNTIMEPOLICY_PROCESSING_CLASSES`: default `local_only`.
- `CTI_RAG_RUNTIMEPOLICY_PRIVATE_STATE`: explicit opt-in for private state.
- `CTI_RAG_RUNTIMEPOLICY_EXPECTED_ARTIFACT_SHA256`: optional broker installed-artifact attestation pin.

The adapter sends exact policy Actions for scope admission, model destination authorization, and network destination authorization. These are RuntimePolicy Action.operation values, not broker RPC method names. The broker RPC surface remains the canonical `AuthorityClient` protocol.

A successful scope assessment is retained only in process so the same exact admission can be revalidated at response time. The adapter calls the broker's current revision and `check()`; it never treats a cached decision as valid across a revision change or expiry.

Operator-reviewed exact-action grants must cover the emitted action payload and target. Do not create affirmative live grants from the conformance fixtures.
