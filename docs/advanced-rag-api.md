# Advanced retrieval API

The direct FastAPI application route is:

```text
POST /chat/advanced-retrieval
```

There is no implicit `/api` prefix in the application. Deployments that expose an
outer prefix must configure that in their reverse proxy/gateway and document the
resulting external URL separately.

## Feature flag

The legacy `config.yaml` contains:

```yaml
advanced_rag:
  enabled: false
  config_path: benchmark/advanced/configs/fixture.yaml
  proxy_prefix: ""
```

Advanced retrieval is therefore absent from the legacy application unless an
explicitly validated advanced router is constructed and supplied to the server
factory. A failed advanced request never falls back to the legacy retriever.

## Request

```json
{
  "query": "Map CVE-2026-999999 to CWE",
  "db_id": "fixture-cti",
  "top_k": 12,
  "max_graph_hops": 2,
  "response_mode": "summary",
  "web_search": false
}
```

`top_k` is bounded to 1-50, graph hops to 0-3, and the UTF-8 encoded query to
8192 bytes. Unknown fields are rejected. Caller-supplied principals, policies,
provider endpoints, Cypher, Milvus filters, and `web_search=true` are not accepted.

## Authorization

The route authenticates the user and resolves the server-owned corpus grant before
constructing its runtime/backends. The canonical principal is the authenticated
`User.id` namespace established in Prompt 15. Request-body `user_id` or legacy
knowledge-database ownership does not participate in authorization.

`response_mode=full` additionally requires the server-owned `evidence:debug`
capability. Debug authorization is independent of the response-mode string.

## Response

The endpoint returns retrieval context rather than secretly generating an answer:

- `retrieval_run_id`
- `domain`
- `snapshot_id`
- `status` (`ok`, `no_evidence`, `partial`)
- `answer_context`
- `citations`
- authorized `candidates` only in permitted full/debug mode
- `channel_status`
- `degraded_channels`
- `truncated`
- `timings`
- `model_fingerprints`

A runtime finalizer executes immediately before serialization so policy/grant or
withdrawal changes cannot be ignored at the API boundary.

## Failure semantics

- missing/invalid identity: `401`
- unknown or unauthorized corpus: indistinguishable `403`
- malformed request: `422`
- authorization store or all retrieval channels unavailable: `503`
- successful empty retrieval: `200` with `status=no_evidence`

There is no legacy fallback on an advanced failure.

## Fixture application

`rag.api.advanced_app.create_fixture_app()` accepts injected identity, access-store,
and retrieval runtime providers. Importing the module does not construct MySQL,
Redis, RabbitMQ, GPU, Milvus, or Neo4j services. The fixture profile additionally
requires outbound networking, downloads, web search, and the service Milvus backend
to be disabled. Local fixture runtimes may register the existing exact, lexical,
deterministic dense, and catalog-backed graph channels.

Synthetic fixture success establishes mechanics only; it is not a retrieval-quality
or deployment-promotion claim.
