# Evidence runtime deployment profiles and recovery

Phase 22 adds additive deployment contracts; it does not replace or start the legacy `docker-compose.yml`. Operators choose a profile, provide a configurable `CTI_RAG_DATA_ROOT`, and map the profile to the existing services in their environment.

Profiles:
- `fixture`: SQLite metadata/catalog, immutable filesystem object store, fixture lexical/dense; no egress.
- `text-mvp`: API + worker + metadata/object/lexical/dense + Redis/RabbitMQ; external egress denied by default.
- `analytical`: text-MVP plus DuckDB and Neo4j; external egress denied by default.
- `full-research`: analytical profile plus optional reranker/generator/web/OpenCTI/RuntimePolicy integrations. External egress is an explicit allowlist and optional integrations remain disabled until configured/authorized.

Profile files contain secret **names**, never secret values. Only the API port is externally exposed by the profile contract. Stateful backend storage remains writable inside its data root; read-only/restricted mounts should be used only for configuration/source inputs that do not need mutation.

## Local fixture smoke

```bash
export CTI_RAG_DATA_ROOT="$PWD/.cti-rag-data"
python scripts/phase22_profile_smoke.py --profile deploy/profiles/fixture.json --root "$CTI_RAG_DATA_ROOT/fixture-smoke"
```

This creates isolated local fixture storage and does not start or alter the user's running services.

## Backup and health

```bash
python scripts/phase22_recovery.py health --root "$CTI_RAG_DATA_ROOT/fixture-smoke"
python scripts/phase22_recovery.py backup --root "$CTI_RAG_DATA_ROOT/fixture-smoke" --backup "$CTI_RAG_DATA_ROOT/backups/fixture-001"
```

A backup contains canonical metadata, the snapshot catalog/pointer/revocations, and checksum-verified immutable object bytes. Secrets are deliberately not copied; operators must maintain their secret-manager recovery procedure separately.

## Restore rehearsal

Restore into a new isolated root first:

```bash
mkdir -p "$CTI_RAG_DATA_ROOT/restore-rehearsal"
python scripts/phase22_recovery.py restore --root "$CTI_RAG_DATA_ROOT/restore-rehearsal" --backup "$CTI_RAG_DATA_ROOT/backups/fixture-001"
python scripts/phase22_recovery.py health --root "$CTI_RAG_DATA_ROOT/restore-rehearsal"
python scripts/phase22_recovery.py rebuild-fixture-index --root "$CTI_RAG_DATA_ROOT/restore-rehearsal" --output "$CTI_RAG_DATA_ROOT/restore-rehearsal/rebuilt-fixture-index.json"
```

Derived backend indexes are rebuildable and are not authoritative backups. The fixture rebuild command verifies the identity/citation material available from the restored published manifest. Production MySQL/Milvus/Neo4j rebuild procedures remain service-specific gates until those services are available.

## Rollback

```bash
python scripts/phase22_recovery.py rollback --root "$CTI_RAG_DATA_ROOT/restore-rehearsal" --manifest <previous-manifest-id>
```

Rollback only moves the atomic catalog pointer to an already-serviceable immutable generation. It does not bypass current revocations.

## Cache and tombstone behavior

Result-cache identities include principal/security namespace, effective scope, policy epoch, normalized query and exact IDs, snapshot, temporal mode/cutoff, plan/config/model fingerprints, locale, and cache kind. Private query and embedding caches use separate physical stores. Empty and failed retrievals have distinct states. Revocation invalidation deletes dependent cache entries independently of TTL.

## Telemetry

Default telemetry stores query digests plus bounded stage metrics. Raw queries, snippets, prompts, credentials, and private samples are not default telemetry fields. Raw debug traces require a separately authorized protected trace store. GPU/VRAM concurrency metrics are reported only when a runtime sampler exists; otherwise the status remains `not_available`.
