# Advanced service compatibility matrix

The advanced service stack is physically separated from the legacy Milvus and Neo4j paths. Advanced services use a separate Compose project, loopback host ports, internal networks, named volumes, namespaces/labels and explicit advanced credentials. No legacy endpoint, credential or volume is accepted as a fallback.

| Component | Pinned / intended version | Validation status in implementation sandbox |
| --- | --- | --- |
| Python | 3.11 target | exact P10/P11 full-checkout chain `not_run`; sandbox is Python 3.13.5 |
| Milvus server | 2.3.4 | live container `not_run` |
| PyMilvus client | 2.3.7 | pinned; live roundtrip `not_run` |
| etcd | 3.5.5 | compose-declared; live service `not_run` |
| MinIO | RELEASE.2023-03-20T20-16-18Z | compose-declared; live service `not_run` |
| Neo4j server | 5.15 Community | compose-declared; live compatibility `not_run` |
| Neo4j Python driver | 5.15.0 | pinned; live compatibility `not_run` |
| Fake/injected Milvus client | in-process | focused unit gate passed |
| Catalog-backed graph reader/writer | in-process | focused graph mechanics gate passed |

## Isolation contract

- Advanced Milvus publishes only on loopback `${ADVANCED_MILVUS_PORT:-19531}` and uses `cti-rag-advanced-milvus-internal` plus `cti-rag-advanced-milvus-*` volumes.
- etcd and MinIO have no host-published ports. MinIO credentials are mandatory environment placeholders with no repository default.
- Advanced Neo4j publishes HTTP/Bolt only on loopback `${ADVANCED_NEO4J_HTTP_PORT:-7475}` / `${ADVANCED_NEO4J_BOLT_PORT:-7689}` and uses `cti-rag-advanced-neo4j-internal` plus dedicated data/log volumes.
- Neo4j requires `ADVANCED_NEO4J_USERNAME` and `ADVANCED_NEO4J_PASSWORD`; the advanced graph writer accepts an explicit non-legacy backend identity and contains no fallback to the legacy graph manager.
- Neo4j Community multi-database behavior and labels are not treated as a security boundary. The isolation claim depends on the separate service, network, ports, volumes and credentials.
- A release gate must prove that supplied legacy credentials cannot authenticate to the advanced Neo4j endpoint and that a configured legacy endpoint cannot see an advanced isolation probe.
- The default Milvus compatibility profile still does not establish authenticated Milvus users; restricted-evidence Milvus promotion therefore remains blocked.

## Neo4j integration environment

POSIX placeholders:

```sh
export ADVANCED_NEO4J_USERNAME="<advanced-user>"
export ADVANCED_NEO4J_PASSWORD="<advanced-password>"
export ADVANCED_NEO4J_INTEGRATION_URI="bolt://127.0.0.1:7689"
# Optional legacy-isolation release gate:
export LEGACY_NEO4J_INTEGRATION_URI="<legacy-bolt-uri>"
export LEGACY_NEO4J_USERNAME="<legacy-user>"
export LEGACY_NEO4J_PASSWORD="<legacy-password>"
```

PowerShell placeholders:

```powershell
$env:ADVANCED_NEO4J_USERNAME="<advanced-user>"
$env:ADVANCED_NEO4J_PASSWORD="<advanced-password>"
$env:ADVANCED_NEO4J_INTEGRATION_URI="bolt://127.0.0.1:7689"
$env:LEGACY_NEO4J_INTEGRATION_URI="<legacy-bolt-uri>"
$env:LEGACY_NEO4J_USERNAME="<legacy-user>"
$env:LEGACY_NEO4J_PASSWORD="<legacy-password>"
```

## Release blockers

Fake/in-memory mechanics are not real-service compatibility evidence. Promotion remains blocked until the exact Python 3.11 chain is green, Compose validates, the isolated Milvus and Neo4j services start, real client/server roundtrips pass, both legacy-isolation gates pass, and any restricted-evidence service has an authenticated configuration appropriate for that data.