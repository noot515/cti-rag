# Current state and sequencing handoff

Prompt 05 begins from Prompt 04 documented head `19f7e6fe86fd6e3eb5b61cb6ece9d44143482bac` on `feat/advanced-04-cti-domain-adapter`. Its implementation is stacked on `feat/advanced-05-durable-evidence-catalog`; the Prompt 05 code commit is `fc439d7fb62733b359df2c305b43d96971e9bd78`.

Reconciliation notes:

1. Prompt 04 reused and hardened the predecessor CTI package. It added the one generic requirement needed by storage: `NormalizedEvidenceBatch` can carry chunks.
2. Prompt 05 does not reuse `KBDBManager`, `KnowledgeDatabase`, MySQL ownership, caller-provided legacy `user_id`, or tracked `saves/data/knowledge.db` as an authorization/catalog boundary. The advanced store is separate and explicitly constructed.
3. Raw payload publication precedes SQLite references: temp write -> flush/fsync -> atomic rename -> verified content, followed by one catalog transaction. A crash in between may leave an orphan raw file but cannot leave a catalog reference to absent bytes.
4. Every catalog identity/join is scoped by `domain` and `scope_id`; logical UIDs remain globally stable and may intentionally appear in more than one scope.
5. Revisions are immutable and capture/poll observations are separate metadata. Exact external IDs are many-to-many. Source/raw links preserve source identity, normalizer version and snapshot capture identity.
6. Snapshot storage is deliberately not publication. New snapshots are inactive and Prompt 05 contains no activation/backend projection behavior.
7. Raw metadata lookup and hydration require both policy authorization and evidence linkage; authorization is checked before digest existence is disclosed.
8. Prompt 06 is next after review and exact-environment validation. Milvus/Neo4j projection, snapshot activation, retrieval orchestration, OpenCTI sync, garbage collection and service promotion remain future phases.

Validation state: Prompt 05 focused sandbox tests passed (`12 passed`); combined Prompt 04/05 sandbox tests passed (`40 passed`), plus compile/diff checks. Exact Prompt 04/05 Python 3.11 and full-repository collection are `not_run` on the new stack and must be rerun rather than inferred from the predecessor result.
