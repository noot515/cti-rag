# Advanced service compatibility matrix

The advanced service stack is isolated from the legacy Milvus deployment by a different Compose project, container names, Docker network, named volumes, collection namespace and loopback host port. No legacy Milvus host, port, token, collection prefix or volume is used as a fallback.

| Component | Pinned / intended version | Validation status in implementation sandbox |
| --- | --- | --- |
| Python | 3.11 target | `not_run` for the exact P09 branch; sandbox is Python 3.13.5 |
| Milvus server | 2.3.4 | `not_run` against a live container |
| PyMilvus client | 2.3.7 | pinned in `requirements-advanced-services.txt`; live matrix `not_run` |
| etcd | 3.5.5 | compose-declared; live service `not_run` |
| MinIO | RELEASE.2023-03-20T20-16-18Z | compose-declared; live service `not_run` |
| Fake injected Milvus client | in-process | unit gate passed |

The 2.3.x Milvus family is paired with PyMilvus 2.3.7 because the Milvus SDK compatibility table recommends PyMilvus 2.3.7 for Milvus 2.3.x. The exact server/client pair still requires the real integration gate before promotion.

## Isolation contract

- Advanced Milvus publishes only on loopback port `${ADVANCED_MILVUS_PORT:-19531}`; the legacy route is not reused.
- etcd and MinIO have no host-published ports and live only on `cti-rag-advanced-milvus-internal`.
- Advanced volumes are `cti-rag-advanced-milvus-*`; no legacy volume is mounted.
- Advanced collection names use an `adv_` namespace plus scope/generation identity. The adapter has no collection-drop API and refuses legacy prefixes.
- MinIO credentials are mandatory environment placeholders with no repository default. They are not printed by the validation code.
- The default isolated Compose file does not enable Milvus user authentication. Therefore real restricted-evidence ingestion remains blocked until an authenticated advanced Milvus configuration and separate advanced credential are supplied and tested. The services profile is for synthetic/public compatibility validation only.
- A release gate must demonstrate that the configured legacy endpoint cannot see the advanced collection. The integration test records this separately when `LEGACY_MILVUS_INTEGRATION_URI` is supplied.

## Release blockers

A fake-client unit pass is not a real-service compatibility claim. Promotion remains blocked until the isolated Compose configuration parses, Milvus 2.3.4 starts, the PyMilvus 2.3.7 roundtrip integration passes, the legacy-endpoint isolation test passes, and the exact Python 3.11 repository validation is green.
