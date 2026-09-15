# Advanced CTI RAG Implementation and Evaluation Plan

**Repository:** `noot515/cti-rag`  
**Baseline:** fork of ThreatRAG / CTI-RAG  
**Primary goal:** evolve the existing ThreatRAG retrieval stack into a provenance-preserving, STIX-aware, OpenCTI-backed hybrid RAG system that can be evaluated rigorously with CTIConnect and repository-native benchmarks.

---

## 1. Executive summary

The repository already contains most of the runtime plumbing needed for a strong cybersecurity RAG system:

- Milvus dense-vector retrieval in `packages/core/knowledgebase.py`
- BM25 support in `packages/core/bm25_retriever.py`
- entity extraction and entity candidate indexing in `packages/core/entity_extractor.py` and `packages/core/entity_candidate_index.py`
- Neo4j graph storage/querying in `packages/core/graphbase.py`
- graph indexing in `packages/core/graph_indexer.py`
- a staged hybrid retriever in `packages/core/retriever.py`
- reranking in `packages/models/rerank_model.py`
- API/runtime code under `rag/`
- Redis/RabbitMQ workers and session infrastructure
- an existing benchmark harness in `benchmark/query_test.py`
- Dockerized Milvus, Neo4j, MySQL, Redis, RabbitMQ, MinIO, Ollama, API, and worker services.

The advanced system should **not** replace this stack. It should add a normalized cyber-threat-intelligence layer, deterministic indexing, explicit provenance, better candidate fusion, and a reproducible evaluation harness.

The target architecture is:

```text
                     EXTERNAL CTI SOURCES

 ATT&CK   CVE/NVD   CWE   CAPEC   KEV   ATLAS   Reports   MISP ...
    \        |       |      |      |      |        |       /
     \       |       |      |      |      |        |      /
                         OpenCTI
                  canonical CTI source
                      STIX 2.1 graph
                           |
                    PyCTI / GraphQL
                           |
                    OpenCTI adapter
                           |
                  normalized CTI schema
                           |
             +-------------+-------------+
             |                           |
             v                           v
        Milvus index                 Neo4j index
   dense chunk/object search      typed graph/path search
             |                           |
             +-----------+---------------+
                         |
                 lexical BM25 index
                         |
                         v
               Retrieval Orchestrator
  exact IDs + dense + lexical + entity + graph + metadata
                         |
                     fusion
                  weighted RRF
                         |
                     reranker
                         |
                context packer
          provenance + citations retained
                         |
                         v
                    RAG / Agent
                         |
                policy hook boundary

                   EVALUATION PLANE
                         |
         repository benchmark + CTIConnect
```

OpenCTI is the **canonical CTI data plane**. Milvus, Neo4j, and the lexical index are **derived retrieval indexes** and must be rebuildable from canonical objects.

---

# 2. Current repository assessment

## 2.1 Components to preserve

Do not rewrite the following unless a phase explicitly requires a compatibility change:

| Existing component | Preserve as | Planned role |
|---|---|---|
| `packages/core/knowledgebase.py` | dense-index abstraction | Milvus chunk/object retrieval |
| `packages/core/graphbase.py` | graph abstraction | Neo4j entity/path retrieval |
| `packages/core/retriever.py` | public retrieval entry point | facade over a new orchestrator |
| `packages/core/entity_extractor.py` | entity extraction provider | query/report entity extraction |
| `packages/core/entity_candidate_index.py` | candidate linker | entity resolution helper |
| `packages/core/bm25_retriever.py` | lexical scoring code | refactor into persistent independent lexical retrieval |
| `packages/models/rerank_model.py` | reranking provider abstraction | final candidate reranking |
| `packages/manager/*` | service managers | persistence/database access |
| `rag/api/*` | API layer | expose advanced retrieval without changing existing endpoints initially |
| `rag/mq/*` | async execution | ingestion/sync/index jobs later |
| `benchmark/query_test.py` | legacy answer benchmark | retain as regression suite |
| `docker-compose.yml` | ThreatRAG runtime | keep OpenCTI logically separate initially |

## 2.2 Baseline weaknesses to address before OpenCTI

These issues should be fixed early because they make later comparisons noisy or non-reproducible.

### A. BM25 is not currently an independent retrieval channel

`KnowledgeBase.query()` first performs dense search, then fits BM25 on the already-retrieved dense candidates. That makes BM25 a local reordering mechanism rather than a true lexical retriever.

**Required change:** build a persistent per-knowledge-base lexical index over the complete indexed corpus, then run lexical and dense retrieval independently.

### B. Reranking is duplicated

`KnowledgeBase.query()` may rerank vector/BM25 results, and `Retriever._rerank_stage()` reranks the merged vector/graph candidates again.

**Required change:** make candidate generation score-only. Perform one final reranking pass after candidate fusion.

### C. Provenance is lost during graph retrieval

`Retriever._graph_retrieval_stage()` converts graph edges to strings before reranking. This removes graph path identity, STIX IDs, source information, confidence, timestamps, and evidence provenance.

**Required change:** all retrieval stages return typed candidate objects. Convert them to text only in the context-packing layer.

### D. Milvus IDs are random

`KnowledgeBase.add_documents()` currently generates random integer IDs. Re-indexing the same data therefore creates different identities and complicates idempotent sync, deduplication, benchmark reproducibility, and provenance.

**Required change:** use deterministic chunk identity.

### E. Entity extraction is language-specific in the advanced path

The five-stage hybrid path currently invokes entity extraction with `language="chinese"`.

**Required change:** add `auto`, `en`, and `zh` language selection, with `auto` as the default for CTI data.

### F. Evaluation currently emphasizes answer overlap, not retrieval quality

`benchmark/query_test.py` can score generated answers, but the advanced system also needs retrieval metrics, graph-path metrics, citation metrics, and latency metrics.

### G. Web search contaminates offline evaluation

`config.yaml` enables web search by default. Offline comparisons must disable web search so all systems answer from the same corpus.

---

# 3. Design principles

The implementation must follow these rules.

## 3.1 Canonical data vs derived indexes

OpenCTI/STIX objects are canonical. Milvus, Neo4j, BM25, and caches are derived representations.

Never make Milvus or Neo4j the only location containing information required to reconstruct provenance.

## 3.2 Every result retains provenance

A retrieval candidate must retain at minimum:

- normalized object/chunk ID
- upstream source system
- upstream source object ID
- STIX ID if present
- object type
- source URL if present
- source title/name
- source timestamp
- modified timestamp
- confidence
- markings/TLP
- parent object ID
- chunk index
- retrieval channel
- channel-specific raw score
- fused score
- reranker score
- graph path when applicable.

## 3.3 Retrieval channels remain independently measurable

Dense, lexical, exact/entity, and graph retrieval must each be callable separately so they can be ablated and benchmarked.

## 3.4 Fusion occurs before reranking

The pipeline should be:

```text
query analysis
    -> parallel candidate generation
    -> deduplication
    -> score normalization / weighted RRF
    -> diversity filtering
    -> single reranking pass
    -> context packing
```

Do not rerank separately inside each retrieval backend.

## 3.5 Evaluation is deterministic by default

Default test/evaluation runs must not require:

- web search
- a remote LLM
- a remote embedding API
- a mutable external CTI feed.

Use fixtures/mocks for unit and integration tests. Keep live-model/live-OpenCTI tests under explicit markers.

## 3.6 Security and markings are data, not decoration

Preserve TLP/marking information and make it available to a later policy filter. Do not silently strip it during normalization.

---

# 4. Proposed package structure

Add the following without moving existing modules during the first implementation pass:

```text
packages/
├── core/
│   ├── retriever.py                 # compatibility facade
│   ├── retrieval_orchestrator.py    # NEW
│   ├── candidate.py                 # NEW
│   ├── fusion.py                    # NEW
│   ├── context_packer.py            # NEW
│   ├── lexical_index.py             # NEW
│   ├── query_planner.py             # NEW
│   ├── knowledgebase.py             # modify incrementally
│   └── graphbase.py                 # modify incrementally
│
├── cti/                             # NEW
│   ├── __init__.py
│   ├── schema.py
│   ├── ids.py
│   ├── normalize.py
│   ├── provenance.py
│   ├── markings.py
│   ├── mappings.py
│   └── validation.py
│
├── integrations/                    # NEW
│   └── opencti/
│       ├── __init__.py
│       ├── client.py
│       ├── models.py
│       ├── reader.py
│       ├── normalizer.py
│       ├── sync.py
│       └── checkpoint.py
│
├── indexing/                        # NEW
│   ├── __init__.py
│   ├── chunker.py
│   ├── vector_indexer.py
│   ├── graph_indexer.py
│   ├── lexical_indexer.py
│   ├── orchestrator.py
│   └── manifests.py
│
└── manager/
    ├── ... existing ...
    └── cti_sync_manager.py          # NEW, optional after schema migration

benchmark/
├── query_test.py                    # existing legacy benchmark
├── advanced/                        # NEW
│   ├── run_retrieval_eval.py
│   ├── run_answer_eval.py
│   ├── metrics.py
│   ├── report.py
│   ├── ablations.py
│   └── configs/
│       ├── offline.yaml
│       ├── cticonnect.yaml
│       └── live_opencti.yaml
└── cticonnect/                      # NEW adapter; do not copy dataset blindly
    ├── adapter.py
    └── README.md

tests/
├── unit/
│   ├── cti/
│   ├── retrieval/
│   └── indexing/
├── integration/
│   ├── test_milvus_indexing.py
│   ├── test_neo4j_indexing.py
│   ├── test_hybrid_retrieval.py
│   └── test_opencti_adapter.py
├── fixtures/
│   └── cti/
└── e2e/
    └── test_advanced_rag_e2e.py

docs/
└── advanced-rag-implementation-plan.md
```

Do not rename existing directories in the first five PRs. The goal is to keep upstream behavior bisectable.

---

# 5. Internal CTI data contract

Implement the internal contract before writing an OpenCTI adapter.

## 5.1 `CtiObject`

Create a Pydantic model in `packages/cti/schema.py`.

Minimum fields:

```python
class CtiObject(BaseModel):
    uid: str
    object_type: str
    source_system: str
    source_object_id: str
    stix_id: str | None = None
    name: str | None = None
    description: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    confidence: int | None = None
    labels: list[str] = []
    markings: list[str] = []
    external_references: list[ExternalReference] = []
    aliases: list[str] = []
    raw_relationships: list[str] = []
    raw: dict[str, Any] | None = None
```

`uid` must be stable across repeated syncs.

Recommended identity rule:

```text
uid = sha256("{source_system}:{source_object_id}")
```

If `stix_id` is present and stable, `source_object_id` should normally be the STIX ID.

## 5.2 `CtiRelationship`

```python
class CtiRelationship(BaseModel):
    uid: str
    source_uid: str
    target_uid: str
    relationship_type: str
    source_system: str
    source_relationship_id: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    confidence: int | None = None
    markings: list[str] = []
    description: str | None = None
```

Identity:

```text
sha256("{source_system}:{source_rel_id or source_uid + ':' + relationship_type + ':' + target_uid}")
```

## 5.3 `CtiChunk`

A chunk is the unit used by dense and lexical retrieval.

```python
class CtiChunk(BaseModel):
    uid: str
    object_uid: str
    chunk_index: int
    chunk_kind: str
    text: str
    title: str | None = None
    object_type: str
    source_system: str
    source_object_id: str
    stix_id: str | None = None
    source_url: str | None = None
    modified_at: datetime | None = None
    confidence: int | None = None
    markings: list[str] = []
    metadata: dict[str, Any] = {}
```

Identity:

```text
chunk_uid = sha256("{object_uid}:{chunk_kind}:{chunk_index}:{normalized_text_hash}")
```

## 5.4 `RetrievalCandidate`

This is the critical contract between retrieval stages.

```python
class RetrievalCandidate(BaseModel):
    candidate_id: str
    object_uid: str
    chunk_uid: str | None = None
    object_type: str
    text: str
    provenance: Provenance

    channels: set[str]
    dense_score: float | None = None
    lexical_score: float | None = None
    exact_score: float | None = None
    graph_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None

    graph_path: list[GraphPathStep] | None = None
    metadata: dict[str, Any] = {}
```

Never replace this object with a plain string until `context_packer.py`.

---

# 6. Deterministic ID migration

## 6.1 Do not mutate existing production collections in place initially

The current Milvus collection uses an integer primary key and random IDs. Create a **versioned v2 collection** for advanced CTI data rather than rewriting existing user KB collections.

Recommended naming:

```text
legacy user KB: kb_<existing-id>
advanced CTI:   cti_v2_<dataset-or-tenant>
```

## 6.2 Stable INT64 helper

To remain compatible with the current integer primary-key design, add:

`packages/cti/ids.py`

```python
def stable_int64_id(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF
```

Also store the complete string `chunk_uid` as a VARCHAR field so collisions can be detected.

## 6.3 New Milvus schema

Create an explicit v2 schema rather than relying heavily on dynamic fields.

Minimum static fields:

```text
id                  INT64 primary key
vector              FLOAT_VECTOR
chunk_uid           VARCHAR(64)
object_uid          VARCHAR(64)
object_type         VARCHAR(64)
source_system       VARCHAR(128)
source_object_id    VARCHAR(512)
stix_id             VARCHAR(512)
source_url          VARCHAR(2048)
title               VARCHAR(1024)
text                VARCHAR / dynamic as supported
chunk_kind          VARCHAR(64)
chunk_index         INT64
modified_epoch      INT64
confidence          INT64
marking_summary     VARCHAR(256)
```

Keep dynamic metadata enabled for source-specific fields.

## 6.4 Idempotency test

Index the same fixture twice and assert:

- collection row count is unchanged
- chunk IDs are identical
- Neo4j object counts are unchanged
- relationship counts are unchanged
- retrieval result IDs are identical.

This is a release gate.

---

# 7. OpenCTI integration

## 7.1 Deployment strategy

Do **not** initially merge the entire OpenCTI stack into the existing `docker-compose.yml`.

Reason: OpenCTI has its own Elasticsearch/OpenSearch, Redis, RabbitMQ, object storage, workers, and connectors. Trying to share the existing ThreatRAG infrastructure in the first implementation will make failures difficult to isolate.

Use the official OpenCTI Docker deployment separately and connect over HTTP.

ThreatRAG configuration:

```env
OPENCTI_ENABLED=false
OPENCTI_URL=http://host.docker.internal:8080
OPENCTI_TOKEN=
OPENCTI_VERIFY_TLS=true
OPENCTI_PAGE_SIZE=100
OPENCTI_SYNC_BATCH_SIZE=250
OPENCTI_SYNC_LOOKBACK_SECONDS=300
```

Add corresponding configuration parsing to `packages/config/__init__.py`.

## 7.2 Client

Add `pycti` to the research/advanced requirements first, not the minimal worker requirements unless a worker directly performs sync.

Implement `packages/integrations/opencti/client.py` as the only module allowed to instantiate `OpenCTIApiClient`.

Responsibilities:

- connection setup
- timeout/retry policy
- health/readiness check
- paginated reads
- object lookup by ID
- relationship lookup
- query by `updated_at`/modified checkpoint
- error translation into repository-specific exceptions.

Do not let `packages/core/retriever.py` import `pycti` directly.

## 7.3 Read path first

Phase 1 OpenCTI support is read-only.

The RAG system should read data from OpenCTI and build derived indexes. It must not create or mutate OpenCTI entities in this project phase.

## 7.4 Object types for first milestone

Support only these initially:

1. ATT&CK attack patterns / techniques
2. vulnerabilities / CVEs
3. CWE objects or normalized CWE knowledge objects
4. CAPEC attack patterns
5. reports
6. relationships connecting those objects.

Then add:

- threat actors / intrusion sets
- malware
- tools
- campaigns
- indicators
- observables
- ATLAS objects
- D3FEND objects
- KEV metadata.

## 7.5 Normalization

`packages/integrations/opencti/normalizer.py` converts OpenCTI/PyCTI objects into `CtiObject` and `CtiRelationship` only.

No Milvus or Neo4j calls are allowed in the normalizer.

## 7.6 Checkpointed sync

Start with polling. Do not start with a live event stream.

Add a sync checkpoint containing:

```text
source_system
last_successful_modified_at
last_successful_object_id
last_run_started_at
last_run_completed_at
status
objects_seen
objects_changed
objects_failed
```

Use a small lookback window when querying modified objects to tolerate clock/order issues; deduplication makes reprocessing safe.

After polling is reliable, add OpenCTI streaming as an optional later phase.

---

# 8. Indexing pipeline

## 8.1 Index manifest

Every indexing run should emit a manifest:

```json
{
  "run_id": "...",
  "source": "opencti",
  "started_at": "...",
  "completed_at": "...",
  "objects_read": 0,
  "objects_normalized": 0,
  "chunks_generated": 0,
  "vector_upserts": 0,
  "graph_node_upserts": 0,
  "graph_edge_upserts": 0,
  "lexical_upserts": 0,
  "failures": [],
  "checkpoint_before": "...",
  "checkpoint_after": "..."
}
```

Store manifests under `saves/index_manifests/` in development. If production persistence is later required, move them into a database table.

## 8.2 Chunking policy

Do not use one generic chunking strategy for all STIX objects.

Recommended chunk kinds:

### ATT&CK / CAPEC / CWE

- `summary`
- `description`
- `procedure_examples`
- `mitigations`
- `detection`
- `references`

### CVE

- `summary`
- `affected_products`
- `severity`
- `weakness_mapping`
- `references`

### Report

- heading-aware body chunks
- executive summary
- indicators/entities section
- techniques section.

Target chunk size should be configured in tokens, not characters. Start with approximately 350-600 tokens and 50-100 token overlap for long prose. Structured small objects should often remain one chunk.

## 8.3 Vector indexing

Implement `packages/indexing/vector_indexer.py`.

Operations:

- validate `CtiChunk`
- derive deterministic numeric ID
- batch embeddings
- upsert to Milvus
- preserve all provenance fields
- detect chunk UID collision
- record failures in manifest.

Do not delete/recreate the entire collection during incremental sync.

## 8.4 Neo4j indexing

Implement `packages/indexing/graph_indexer.py` independently from the current free-form document graph extraction.

Canonical node shape:

```text
(:CtiObject {
  uid,
  object_type,
  source_system,
  source_object_id,
  stix_id,
  name,
  confidence,
  created_at,
  modified_at,
  marking_summary
})
```

Add additional semantic labels where safe, for example:

```text
:CtiObject:AttackPattern
:CtiObject:Vulnerability
:CtiObject:Weakness
:CtiObject:Report
:CtiObject:ThreatActor
:CtiObject:Malware
```

Create a unique constraint on `CtiObject.uid`.

Relationships should preserve the upstream relation in properties even if a normalized Neo4j type is used.

Preferred relation representation:

```text
(a)-[:CTI_RELATION {
    uid,
    relationship_type,
    source_system,
    confidence,
    modified_at
}]->(b)
```

This avoids creating arbitrary unsafe Cypher relationship types from untrusted source strings.

## 8.5 Lexical indexing

Refactor BM25 so it indexes the complete corpus.

Create `packages/core/lexical_index.py` with an interface:

```python
class LexicalIndex(Protocol):
    def rebuild(self, chunks: Iterable[CtiChunk]) -> None: ...
    def upsert(self, chunks: Iterable[CtiChunk]) -> None: ...
    def delete(self, chunk_uids: Iterable[str]) -> None: ...
    def search(self, query: str, *, top_k: int, filters: dict | None = None) -> list[RetrievalCandidate]: ...
```

The first implementation may wrap the existing BM25 code and persist the corpus/index metadata locally. Keep the interface backend-agnostic so OpenSearch can be substituted later without modifying the orchestrator.

---

# 9. Advanced retrieval pipeline

Implement the advanced pipeline in a new `RetrievalOrchestrator`. Keep `Retriever.retrieval()` as the compatibility entry point.

## 9.1 Stage 0: query analysis

Create `packages/core/query_planner.py`.

Return a deterministic `QueryPlan` structure:

```python
class QueryPlan(BaseModel):
    query: str
    normalized_query: str
    language: Literal["en", "zh", "mixed", "unknown"]
    task_type: Literal[
        "entity_lookup",
        "cross_source_mapping",
        "multi_hop",
        "report_attribution",
        "synthesis",
        "general"
    ]
    identifiers: list[str]
    entities: list[str]
    desired_object_types: list[str]
    time_range: TimeRange | None
    use_dense: bool
    use_lexical: bool
    use_graph: bool
    max_graph_hops: int
```

Deterministic regex extraction should handle at minimum:

- CVE IDs
- CWE IDs
- CAPEC IDs
- ATT&CK technique/sub-technique IDs
- IPv4/IPv6
- domains
- SHA256/SHA1/MD5 hashes.

Do not require an LLM for identifier extraction.

## 9.2 Stage 1: exact identifier/entity lookup

Exact identifiers should outrank semantic similarity.

Examples:

```text
CVE-2026-12345
CWE-787
CAPEC-100
T1059.001
```

Lookup order:

1. exact canonical/source ID
2. exact alias/name
3. entity-candidate similarity.

Emit `RetrievalCandidate(channel="exact")`.

## 9.3 Stage 2: dense retrieval

Run Milvus independently.

Default starting values:

```text
dense_top_k = 40
```

Do not apply final reranking inside `KnowledgeBase.query()` for advanced-mode requests.

Add an explicit parameter such as:

```python
rerank=False
```

or a new low-level method:

```python
KnowledgeBase.search_candidates(...)
```

so the orchestrator can obtain raw dense candidates.

## 9.4 Stage 3: lexical retrieval

Run BM25 independently over the entire corpus.

Starting value:

```text
lexical_top_k = 40
```

Cyber identifiers and product/version strings make this channel essential.

## 9.5 Stage 4: entity linking

Entity extraction sources:

1. deterministic identifier parser
2. entity candidate index
3. optional model extraction for names not captured by deterministic rules.

Language should be automatic. Do not hard-code Chinese.

Entity linking must return canonical `object_uid` values where possible, not only names.

## 9.6 Stage 5: graph retrieval

Use canonical entity UIDs as graph seeds.

Graph search should support:

- 1-hop neighbors
- bounded 2-3 hop paths
- relationship-type allowlists/filters
- object-type filters
- time filters
- path length penalty
- degree cap to prevent high-degree nodes from dominating.

Recommended initial score:

```text
graph_score =
    seed_confidence
    * relationship_confidence
    * (1 / path_length)
    * relation_prior
```

Do not use unrestricted variable-length Cypher generated directly from the user query in the advanced benchmark path.

Use parameterized query templates for common traversal patterns. LLM-generated Cypher, if retained, should remain a separate experimental mode.

## 9.7 Stage 6: candidate deduplication

Deduplicate primarily by `chunk_uid`, then by `object_uid` + normalized content hash.

When the same candidate arrives from multiple channels, merge the channel scores into one candidate rather than keeping duplicates.

## 9.8 Stage 7: fusion

Use weighted Reciprocal Rank Fusion initially because dense, lexical, and graph scores are not naturally comparable.

Recommended defaults:

```text
k = 60
exact weight   = 1.30
dense weight   = 1.00
lexical weight = 0.90
graph weight   = 1.10
```

Formula:

```text
RRF(candidate) = sum_channel weight(channel) / (k + rank_channel(candidate))
```

Keep weights in config.

Add a minimum source-diversity rule so the top candidate list cannot be filled entirely by near-duplicate chunks from one report.

## 9.9 Stage 8: final reranking

Run exactly one final reranking pass.

Input: top 50-100 fused candidates.  
Output: top 10-20 candidates.

Reranking must return scores attached to `RetrievalCandidate` objects.

Do not format strings such as `[rerank result 1]: ...` inside the reranking function.

## 9.10 Stage 9: context packing

`context_packer.py` should enforce a token budget.

Pack candidates using:

1. rerank score
2. source diversity
3. object diversity
4. graph-path usefulness
5. duplicate suppression
6. token budget.

Render each evidence block with a stable citation ID:

```text
[CTI-001]
Type: vulnerability
ID: CVE-...
Source: NVD/OpenCTI
Modified: ...
Evidence: ...

[CTI-002]
Graph path: CVE -> CWE -> CAPEC -> ATT&CK
Evidence: ...
```

The generation prompt should instruct the model to cite these IDs.

---

# 10. Retrieval API contract

Do not break `/chat/stream` or `/chat/hybrid-retrieval` initially.

Add a new endpoint first:

```text
POST /chat/advanced-retrieval
```

Request:

```json
{
  "query": "Which ATT&CK techniques are connected to CVE-X through CWE/CAPEC?",
  "db_id": "cti_v2_default",
  "response_mode": "full",
  "retrieval_mode": "advanced",
  "top_k": 12,
  "max_graph_hops": 3,
  "web_search": false
}
```

Full response:

```json
{
  "query": "...",
  "query_plan": {},
  "answer_context": "...",
  "citations": [],
  "candidates": [],
  "retrieval_trace": {
    "exact_count": 0,
    "dense_count": 0,
    "lexical_count": 0,
    "graph_count": 0,
    "deduplicated_count": 0,
    "reranked_count": 0
  },
  "timings_ms": {
    "planning": 0,
    "dense": 0,
    "lexical": 0,
    "graph": 0,
    "fusion": 0,
    "reranking": 0,
    "packing": 0,
    "total": 0
  }
}
```

After benchmark parity is demonstrated, route the existing hybrid endpoint to the new orchestrator behind a feature flag.

---

# 11. Configuration

Add an `advanced_rag` section to `config.yaml`.

Suggested initial configuration:

```yaml
advanced_rag:
  enabled: false

  exact:
    enabled: true

  dense:
    enabled: true
    top_k: 40

  lexical:
    enabled: true
    top_k: 40

  graph:
    enabled: true
    max_hops: 2
    max_seed_entities: 8
    max_neighbors_per_node: 30
    top_k: 40

  fusion:
    algorithm: weighted_rrf
    rrf_k: 60
    weights:
      exact: 1.30
      dense: 1.00
      lexical: 0.90
      graph: 1.10

  reranker:
    enabled: true
    input_top_k: 60
    output_top_k: 15

  context:
    max_tokens: 8000
    max_chunks_per_object: 3
    max_chunks_per_source: 5

  provenance:
    required: true

  web_search:
    enabled_in_offline_eval: false
```

Feature flag the complete advanced pipeline until the evaluation gates pass.

---

# 12. CTIConnect integration

CTIConnect should be used as an **external benchmark dependency**, not copied wholesale into the application package.

It currently provides 1,859 QA pairs across nine tasks over heterogeneous CTI sources, including CVE, CWE, CAPEC, ATT&CK, and vendor reports. Its code is MIT licensed and data is CC-BY-4.0; preserve attribution and licensing if benchmark data is vendored.

## 12.1 Preferred integration

Add an adapter under:

```text
benchmark/cticonnect/adapter.py
```

Support two modes:

### Mode A: installed dependency / cloned sibling repo

```text
CTICONNECT_PATH=/path/to/CTIConnect
```

### Mode B: minimal vendored evaluation manifest

Vendor only what is needed and legally permitted, preserving `LICENSE-DATA` and provenance.

Prefer Mode A first.

## 12.2 Task mapping

Map CTIConnect tasks into retrieval categories:

```text
single-object lookup       -> exact + dense + lexical
cross-source mapping       -> exact + graph
multi-hop mapping          -> graph + dense/lexical evidence
report attribution         -> dense + lexical + entity linking
multi-document synthesis   -> all channels + reranker + context packer
```

## 12.3 Do not use CTIConnect answer data during indexing

Ground-truth answers must never enter the retrieval corpus.

Separate:

```text
corpus data -> indexes
queries     -> retrieval
answers     -> evaluation only
```

Add a test that validates the ground-truth answer file path is never passed to an indexer.

---

# 13. Evaluation design

A serious RAG evaluation must distinguish **retrieval quality** from **answer generation quality**.

## 13.1 Retrieval metrics

Calculate at minimum:

- Hit@1, Hit@5, Hit@10
- Recall@5, Recall@10, Recall@20
- MRR
- nDCG@10
- source recall
- object-type recall
- exact identifier recall
- graph path recall for multi-hop tasks.

## 13.2 Citation/provenance metrics

For generated answers:

- citation precision
- citation recall
- unsupported-claim rate
- invalid citation rate
- provenance completeness
- cited-object existence rate.

## 13.3 Answer metrics

Keep the current benchmark answer-overlap score as a legacy metric.

Add:

- normalized exact/substring metrics for identifier answers
- set F1 for lists of CVEs/CWEs/CAPECs/ATT&CK IDs
- LLM-as-judge only as an optional secondary metric
- groundedness against retrieved evidence.

A remote LLM judge must never be the sole acceptance metric.

## 13.4 Systems to compare

Every benchmark report should include these ablations:

```text
B0  current repository baseline
B1  dense only
B2  lexical only
B3  dense + lexical
B4  dense + graph
B5  dense + lexical + graph + RRF
B6  B5 + final reranker
B7  B6 + typed/provenance context packing
B8  OpenCTI-backed B7
```

Optional later ablations:

```text
B9  B8 + learned query planner
B10 B8 + RuntimePolicy retrieval filter
```

## 13.5 Latency metrics

Record:

- p50/p95 total retrieval latency
- p50/p95 per retrieval channel
- reranker latency
- context packing latency
- OpenCTI sync throughput
- indexing throughput.

Offline evaluation should record hardware/model configuration in the report.

---

# 14. Acceptance criteria

Use relative gates before absolute performance claims.

## 14.1 Correctness gates

Required:

- 100% deterministic IDs on repeated indexing
- 0 duplicate canonical objects after an idempotent re-sync
- 0 benchmark answers indexed into retrieval corpora
- 100% returned advanced-mode candidates include provenance
- 100% citations resolve to a returned candidate
- exact CVE/CWE/CAPEC/ATT&CK identifiers are retrievable without an LLM
- web search is disabled in offline evaluation.

## 14.2 Retrieval gates

Before replacing the current hybrid path:

- advanced retrieval must not reduce overall Recall@10 relative to B0
- advanced retrieval should improve the multi-hop/cross-source subset over B0
- B5 must outperform or equal both B1 and B2 on aggregate retrieval recall
- adding the reranker must not reduce relevant-object Recall@10 materially.

Suggested research target, not a hard first-pass requirement:

```text
>= 5 percentage-point absolute improvement
on multi-hop/cross-source Recall@10 vs B0
```

## 14.3 Operational gates

- re-sync after no upstream changes performs zero logical object changes
- service restart preserves indexes/checkpoints
- failed indexing batches can resume
- OpenCTI unavailable -> retrieval over existing indexes still works
- Neo4j unavailable -> degraded dense+lexical mode works
- Milvus unavailable -> degraded lexical+graph mode is explicit, not silent.

---

# 15. Test strategy

## 15.1 Unit tests

### `tests/unit/cti/test_ids.py`

Test:

- stable `uid`
- stable INT64 conversion
- different IDs produce different values in fixture set
- chunk identity changes only when relevant chunk inputs change.

### `tests/unit/cti/test_normalize.py`

Fixture objects:

- attack pattern
- CVE/vulnerability
- CWE
- CAPEC
- report
- relationship.

Assert normalized object fields and provenance.

### `tests/unit/retrieval/test_fusion.py`

Use fixed ranks and verify weighted-RRF output exactly.

### `tests/unit/retrieval/test_candidate_merge.py`

Same chunk from dense and lexical must become one candidate with both channel scores.

### `tests/unit/retrieval/test_query_planner.py`

Cases:

```text
CVE-2026-12345
CWE-787
CAPEC-100
T1059.001
IPv4
hashes
mixed identifier + prose
English CTI question
Chinese CTI question
```

### `tests/unit/retrieval/test_context_packer.py`

Verify:

- token budget
- diversity limits
- citation IDs
- provenance serialization
- no duplicate chunks.

## 15.2 Integration tests

Mark service-dependent tests:

```ini
markers =
    integration: requires local infrastructure
    opencti: requires OpenCTI
    gpu: requires GPU/model runtime
    live_model: invokes a real generation/reranking model
```

### Milvus

- create v2 test collection
- index fixtures
- dense search
- filter by object type/source
- re-index idempotently
- cleanup.

### Neo4j

Fixture graph:

```text
CVE -> CWE -> CAPEC -> ATT&CK
```

Assert:

- one-hop retrieval
- two-hop retrieval
- three-hop retrieval
- path identity
- path provenance
- degree cap.

### Hybrid retrieval

Use deterministic mock embeddings/reranker.

Assert that exact, dense, lexical, and graph candidates fuse into the expected ordering.

### OpenCTI adapter

Prefer recorded JSON fixtures for default CI. Live OpenCTI integration runs only under `-m opencti`.

## 15.3 End-to-end fixture

Build a tiny self-contained corpus:

```text
1 vulnerability
1 CWE
1 CAPEC
2 ATT&CK techniques
1 report
relationships joining them
```

Ask:

```text
Which ATT&CK technique is connected to the vulnerability through its weakness and CAPEC mapping?
```

The test must assert:

- correct object returned
- correct graph path returned
- evidence context contains all required path objects
- citation IDs resolve
- no web search is used.

---

# 16. Benchmark runner

Implement:

```text
python -m benchmark.advanced.run_retrieval_eval \
  --config benchmark/advanced/configs/offline.yaml \
  --output saves/eval/<run-id>/
```

Output directory:

```text
saves/eval/<run-id>/
├── config.snapshot.yaml
├── environment.json
├── per_query.jsonl
├── retrieval_metrics.json
├── answer_metrics.json
├── latency_metrics.json
├── ablation_summary.csv
└── report.md
```

`environment.json` should record:

- git commit
- Python version
- embedding model
- reranker model
- generator model, if used
- Milvus version
- Neo4j version
- OpenCTI version, if used
- CPU/GPU information where available
- timestamp.

---

# 17. Observability

Every advanced request receives a `retrieval_run_id`.

Structured logs should include:

```text
retrieval_run_id
query_hash
query_task_type
exact_count
dense_count
lexical_count
graph_count
fused_count
reranked_count
packed_count
timing_ms
errors/degraded_channels
```

Do not log secrets or raw OpenCTI tokens.

For research runs, store retrieval traces in JSONL so ranking failures can be inspected after the run.

---

# 18. Failure/degradation behavior

The orchestrator must make failures explicit.

## Milvus unavailable

Continue only if lexical or graph channels are available. Add:

```json
"degraded_channels": ["dense"]
```

## Neo4j unavailable

Continue dense + lexical. Do not pretend the graph stage returned zero relevant results; mark it unavailable.

## Reranker unavailable

Return fused RRF ranking and record:

```text
reranker_status = unavailable
```

## OpenCTI unavailable

Existing derived indexes must remain queryable. Only synchronization is unavailable.

## Entity model unavailable

Use deterministic identifiers + aliases + lexical matching.

---

# 19. OpenCTI security / marking handling

Preserve markings in every normalized object and chunk.

Add a retrieval filter interface:

```python
class RetrievalPolicy(Protocol):
    def allow_candidate(self, candidate, principal_context) -> bool: ...
```

For the first implementation use an `AllowAllPolicy` so behavior remains unchanged, but call the hook before context packing.

This creates a clean future integration point for RuntimePolicy without coupling the advanced RAG implementation to another repository now.

Do not implement offensive-action authorization inside the retriever.

---

# 20. Phased implementation plan

## Phase 0 — Baseline and reproducibility

### Goal

Create a trustworthy before-state.

### Changes

1. Add `docs/advanced-rag-implementation-plan.md`.
2. Add baseline benchmark config.
3. Add `benchmark/advanced/report.py` skeleton.
4. Disable web search in offline benchmark config.
5. Record current commit/config/model versions.
6. Run existing `pytest` suite.
7. Run existing `benchmark/query_test.py` on the repository benchmark dataset.
8. Save baseline outputs under `saves/eval/baseline-*` locally; do not commit large generated results.

### Exit criteria

- current unit tests have a recorded pass/fail baseline
- current benchmark produces a reproducible output file
- baseline configuration is committed.

---

## Phase 1 — Typed CTI contracts and deterministic identity

### Goal

Introduce stable internal data structures without changing public retrieval behavior.

### Files

Create:

```text
packages/cti/schema.py
packages/cti/ids.py
packages/cti/provenance.py
packages/core/candidate.py
tests/unit/cti/*
```

### Work

- implement `CtiObject`
- implement `CtiRelationship`
- implement `CtiChunk`
- implement `RetrievalCandidate`
- implement stable UID helpers
- add serialization tests
- add deterministic-ID tests.

### Exit criteria

All new tests pass and existing retrieval behavior is unchanged.

---

## Phase 2 — v2 deterministic indexing

### Goal

Build reproducible Milvus/Neo4j/lexical indexes from normalized CTI fixtures.

### Files

Create:

```text
packages/indexing/vector_indexer.py
packages/indexing/graph_indexer.py
packages/indexing/lexical_indexer.py
packages/indexing/orchestrator.py
packages/indexing/manifests.py
packages/core/lexical_index.py
```

Modify only as needed:

```text
packages/core/knowledgebase.py
packages/core/graphbase.py
packages/manager/milvus_manager.py
packages/manager/neo4j_manager.py
```

### Work

- create v2 Milvus collection schema
- add Neo4j unique constraint
- add graph upsert queries
- create full-corpus lexical index
- create fixture ingestion command
- add manifest output
- test repeated indexing.

### Exit criteria

Same fixture indexed twice produces identical logical state.

---

## Phase 3 — Advanced retrieval orchestrator

### Goal

Replace sequential ad-hoc hybrid retrieval with parallel candidate generation + fusion.

### Files

Create:

```text
packages/core/query_planner.py
packages/core/retrieval_orchestrator.py
packages/core/fusion.py
packages/core/context_packer.py
```

Modify:

```text
packages/core/retriever.py
packages/core/knowledgebase.py
rag/api/routers/chat_api.py
config.yaml
```

### Work

1. deterministic query analysis
2. exact identifier lookup
3. independent dense search
4. independent lexical search
5. canonical entity linking
6. bounded graph search
7. candidate merge
8. weighted RRF
9. one final rerank
10. provenance-preserving context packing
11. new advanced retrieval API.

### Exit criteria

Fixture E2E passes with no external model dependency.

---

## Phase 4 — Retrieval evaluation harness

### Goal

Measure improvements before adding OpenCTI complexity.

### Files

Create:

```text
benchmark/advanced/run_retrieval_eval.py
benchmark/advanced/metrics.py
benchmark/advanced/ablations.py
benchmark/advanced/report.py
benchmark/advanced/configs/offline.yaml
```

### Work

- implement retrieval metrics
- implement latency metrics
- implement candidate trace output
- implement B0-B7 ablations
- run repository-native benchmark.

### Exit criteria

A single command produces a complete Markdown/JSON/CSV evaluation report.

---

## Phase 5 — CTIConnect adapter

### Goal

Evaluate heterogeneous CTI retrieval against an external benchmark.

### Files

Create:

```text
benchmark/cticonnect/adapter.py
benchmark/cticonnect/README.md
benchmark/advanced/configs/cticonnect.yaml
```

### Work

- load CTIConnect tasks
- build corpus-only indexes
- keep ground truth isolated
- map relevant-object IDs into internal IDs
- run B0-B7 where technically applicable
- add per-task reporting.

### Exit criteria

CTIConnect retrieval metrics are reproducible and task-stratified.

---

## Phase 6 — OpenCTI read adapter

### Goal

Make OpenCTI the canonical CTI source without changing retrieval semantics.

### Files

Create:

```text
packages/integrations/opencti/client.py
packages/integrations/opencti/reader.py
packages/integrations/opencti/normalizer.py
packages/integrations/opencti/checkpoint.py
packages/integrations/opencti/sync.py
```

Modify:

```text
packages/config/__init__.py
.env.example
requirements-research.txt
```

### Work

- health/readiness check
- paginated reads
- normalization
- checkpointed polling
- batch indexing through the same Phase 2 indexer
- recorded fixture tests
- optional live OpenCTI integration test.

### Exit criteria

OpenCTI -> normalized objects -> all three indexes -> advanced retrieval works end-to-end.

---

## Phase 7 — Incremental synchronization

### Goal

Make the canonical OpenCTI data plane continuously usable.

### Work

- modified-since polling
- lookback window
- checkpoint persistence
- changed object upserts
- deleted/revoked object handling
- index tombstones
- retry queue
- sync manifests
- metrics.

Use the existing RabbitMQ worker infrastructure if it fits cleanly; do not create a second queue system.

### Exit criteria

- restart resumes from checkpoint
- duplicate events are idempotent
- modified object appears in retrieval after one sync cycle
- deletion/revocation removes or suppresses stale retrieval results.

---

## Phase 8 — OpenCTI-backed benchmark

### Goal

Determine whether OpenCTI-backed normalization/indexing improves retrieval over file-native ingestion.

### Compare

```text
B7 direct corpus indexing
vs
B8 OpenCTI -> normalized -> indexes
```

Measure:

- retrieval accuracy
- graph-path accuracy
- provenance completeness
- ingestion/indexing cost
- query latency
- update latency.

OpenCTI is justified only if its normalization/provenance/maintenance benefits outweigh added operational complexity.

---

## Phase 9 — policy integration hook

### Goal

Expose a clean boundary for RuntimePolicy or another authorization layer.

Do not import another repository directly into core retrieval.

Define interfaces for:

```text
candidate filtering
marking/TLP filtering
retrieval scope
source allowlists
action authorization after retrieval
```

Keep policy evaluation separate from retrieval scoring.

---

# 21. PR sequence

Use small, reviewable PRs.

| PR | Suggested branch | Scope | Must not include |
|---|---|---|---|
| 1 | `feat/cti-contracts` | schemas + stable IDs | retrieval behavior changes |
| 2 | `feat/cti-v2-indexing` | vector/graph/lexical indexes | OpenCTI |
| 3 | `feat/advanced-retrieval-core` | query planner, candidates, RRF, reranker consolidation | OpenCTI |
| 4 | `feat/advanced-retrieval-api` | endpoint/config/trace response | CTIConnect data changes |
| 5 | `feat/retrieval-evaluation` | metrics + ablations | live OpenCTI |
| 6 | `feat/cticonnect-eval` | external benchmark adapter | app runtime dependencies beyond eval |
| 7 | `feat/opencti-reader` | PyCTI read + normalize | streaming |
| 8 | `feat/opencti-sync` | checkpointed incremental sync | RuntimePolicy |
| 9 | `feat/cti-policy-hook` | policy interface | cross-repo hard dependency |

Each PR should include:

- implementation
- tests
- config changes
- doc changes
- benchmark delta if retrieval behavior changes.

---

# 22. CI/test commands

## Fast unit suite

```bash
pytest -q -m "not integration and not opencti and not gpu and not live_model"
```

## Integration suite

```bash
pytest -q -m integration
```

## OpenCTI suite

```bash
pytest -q -m opencti
```

## Legacy benchmark

Preserve the existing command patterns from `benchmark/query_test.py`.

## Advanced offline retrieval benchmark

```bash
python -m benchmark.advanced.run_retrieval_eval \
  --config benchmark/advanced/configs/offline.yaml
```

## CTIConnect

```bash
CTICONNECT_PATH=/path/to/CTIConnect \
python -m benchmark.advanced.run_retrieval_eval \
  --config benchmark/advanced/configs/cticonnect.yaml
```

---

# 23. First fixture to implement

Do not begin with millions of CVEs.

Create a tiny deterministic corpus that proves the architecture:

```text
CVE-TEST-0001
    |
    | has_weakness
    v
CWE-TEST-001
    |
    | represented_by
    v
CAPEC-TEST-001
    |
    | maps_to
    v
ATTACK-T0001

REPORT-TEST-001
    -> mentions CVE-TEST-0001
    -> mentions ATTACK-T0001
```

Include a distractor:

```text
ATTACK-T9999
```

Required queries:

1. exact lookup of the CVE
2. exact lookup of the CWE
3. lexical query containing a product/version string
4. semantic description without identifiers
5. CVE -> CWE query
6. CVE -> CWE -> CAPEC query
7. CVE -> CWE -> CAPEC -> ATT&CK query
8. report-attribution query
9. query whose answer is the distractor, to detect graph over-expansion
10. query with no answer, to test abstention/evidence absence.

This fixture should be the first E2E acceptance test before OpenCTI deployment.

---

# 24. Specific code changes in existing modules

## `packages/core/knowledgebase.py`

### Keep

- Milvus connection lifecycle
- knowledge-base metadata management
- embedding model access
- filtering infrastructure.

### Change

- add a raw candidate search method that does **not** rerank
- add v2 collection creation
- support deterministic IDs/upserts
- stop fitting BM25 only on dense candidates in advanced mode
- return `RetrievalCandidate` through an adapter layer
- keep legacy `query()` behavior behind the current path for compatibility until migration completes.

## `packages/core/retriever.py`

### Keep

- public facade
- traditional mode compatibility
- existing query construction until advanced endpoint is stable.

### Change

Advanced mode should delegate to:

```python
self.advanced_orchestrator.retrieve(...)
```

Do not keep adding stages directly to the existing large `Retriever` class.

## `packages/core/graphbase.py`

### Keep

- connection management
- existing graph APIs for legacy mode.

### Add

- lookup by canonical `uid`
- bounded path queries
- relationship/object-type filters
- deterministic parameterized Cypher for advanced mode
- methods returning typed paths, not strings.

## `packages/core/bm25_retriever.py`

### Keep

- tokenization/scoring utilities where useful.

### Change

Move corpus lifecycle into `lexical_index.py`. BM25 must be independently queryable before dense retrieval.

## `packages/core/entity_extractor.py`

Add automatic language handling and preserve canonical identifiers extracted by deterministic parsers.

## `packages/models/rerank_model.py`

Keep provider abstraction. The orchestrator should call it exactly once per advanced retrieval request.

## `rag/api/routers/chat_api.py`

Add the new advanced endpoint and explicit full/debug response. Do not replace the existing endpoint until benchmark gates pass.

## `benchmark/query_test.py`

Leave legacy behavior intact. New evaluation belongs under `benchmark/advanced/`.

---

# 25. Data-source rollout after OpenCTI works

Add sources in this order:

1. MITRE ATT&CK
2. CVE/NVD
3. CWE
4. CAPEC
5. CISA KEV
6. MITRE ATLAS
7. MITRE D3FEND
8. selected vendor reports
9. MISP/other operational feeds if needed.

For every new source, require:

- source license review
- provenance mapping
- normalization test
- idempotent indexing test
- at least one retrieval benchmark case
- source-specific update strategy.

Do not add a source only because it is available; add it when there is a retrieval task that benefits from it.

---

# 26. Research questions this architecture can test

Once implemented, the repository can support publishable/reproducible questions such as:

1. Does graph retrieval improve cross-ontology CTI mapping over dense+lexical retrieval?
2. Does weighted-RRF outperform score-normalized linear fusion for heterogeneous CTI?
3. Does OpenCTI normalization improve retrieval accuracy or mainly operational maintainability?
4. Which graph-hop limits maximize multi-hop recall without exploding irrelevant context?
5. Does typed provenance-aware context packing reduce unsupported claims?
6. How much does reranking improve retrieval after graph/vector/lexical fusion?
7. Do exact identifier channels materially improve CVE/CWE/CAPEC/ATT&CK tasks?
8. Which source combinations produce the largest marginal gain on CTIConnect task categories?

Do not claim improvement until the relevant ablation demonstrates it.

---

# 27. Definition of done for the advanced RAG milestone

The initial advanced RAG milestone is complete when all of the following are true:

- [ ] typed CTI objects/relationships/chunks exist
- [ ] deterministic IDs are tested
- [ ] v2 Milvus indexing is idempotent
- [ ] Neo4j CTI graph indexing is idempotent
- [ ] full-corpus lexical retrieval exists
- [ ] exact ID retrieval exists
- [ ] dense retrieval exists independently
- [ ] graph retrieval returns typed paths
- [ ] weighted RRF fusion exists
- [ ] final reranking occurs exactly once
- [ ] context packing preserves provenance/citations
- [ ] advanced retrieval endpoint exists
- [ ] offline fixture E2E passes
- [ ] legacy tests still pass or documented regressions are resolved
- [ ] benchmark B0-B7 can run from one command
- [ ] CTIConnect adapter runs without indexing ground-truth answers
- [ ] OpenCTI read adapter works
- [ ] OpenCTI sync is checkpointed and idempotent
- [ ] OpenCTI-backed corpus can be retrieved without OpenCTI being online at query time
- [ ] benchmark report includes retrieval accuracy, citation/provenance quality, and latency
- [ ] feature flag allows fallback to legacy retrieval.

---

# 28. Immediate next implementation step

The first implementation PR should be **Phase 1 only**:

```text
feat/cti-contracts
```

Implement:

```text
packages/cti/__init__.py
packages/cti/schema.py
packages/cti/ids.py
packages/cti/provenance.py
packages/core/candidate.py

tests/unit/cti/test_ids.py
tests/unit/cti/test_schema.py
tests/unit/retrieval/test_candidate.py
```

Do not add OpenCTI or change the live retrieval path in this PR.

The reason for starting here is that deterministic object identity and provenance are dependencies of every later piece: indexing, deduplication, graph paths, citations, incremental sync, CTIConnect evaluation, and RuntimePolicy filtering.

After PR 1 passes, implement the deterministic v2 fixture indexer before touching the current production hybrid pipeline.

---

# 29. External dependency notes

- OpenCTI exposes a GraphQL API and the official `pycti` Python client. Use that client behind a repository-local adapter.
- OpenCTI connectors normalize/import data as STIX 2.1; treat OpenCTI as the canonical normalized CTI layer, not as a vector database.
- CTIConnect should be treated as an evaluation dependency. Keep its benchmark ground truth isolated from indexing.
- Do not couple the advanced RAG implementation directly to RuntimePolicy until retrieval correctness and provenance are stable.

---

# 30. Final recommended order

```text
1. Baseline current repository
2. Add typed CTI contracts
3. Add deterministic identity
4. Build v2 fixture indexes
5. Make BM25 an independent full-corpus channel
6. Add retrieval orchestrator
7. Add weighted-RRF fusion
8. Consolidate to one reranker pass
9. Add provenance-aware context packing
10. Add advanced API
11. Build retrieval benchmark/ablations
12. Add CTIConnect
13. Add OpenCTI read adapter
14. Add checkpointed OpenCTI sync
15. Compare direct vs OpenCTI-backed indexing
16. Add RuntimePolicy hook
17. Expand CTI sources only after measured need
```

This order minimizes the chance that OpenCTI infrastructure complexity hides retrieval bugs and ensures that every architectural addition can be measured against a known baseline.
