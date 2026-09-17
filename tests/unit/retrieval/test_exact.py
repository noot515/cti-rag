from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from packages.domains.cti import CtiDomainAdapter
from packages.evidence.ids import canonical_json
from packages.evidence.policy import Principal, PublicFixturePolicy
from packages.evidence.schema import ExternalIdentifier, SnapshotRef
from packages.evidence.store import EvidenceStore
from packages.indexing.lexical_indexer import ExactProjectionWriter
from packages.indexing.manifests import GenerationManifest, GenerationMember, ProjectionSpec
from packages.indexing.orchestrator import PublicationOrchestrator
from packages.retrieval.exact import ExactIndex

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "cti" / "public_fixture.json"


def _manifest_payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _batch_and_raw_with_body_identifier(body_identifier: str | None = None):
    payload = _manifest_payload()
    if body_identifier:
        payload["objects"][0]["description"] += f" Body-only mention: {body_identifier}."
    batch = CtiDomainAdapter().normalize(payload)
    raw = {}
    for record in payload["objects"] + payload["relations"]:
        encoded = canonical_json(record).encode("utf-8")
        raw[sha256(encoded).hexdigest()] = encoded
    return batch, raw


def _manifest(batch, writer):
    members = [GenerationMember(kind="object", evidence_uid=x.uid, revision_uid=x.revision_uid) for x in batch.objects]
    members += [GenerationMember(kind="relation", evidence_uid=x.uid, revision_uid=x.revision_uid) for x in batch.relations]
    return GenerationManifest.create(
        domain=batch.domain,
        scope_id=batch.scope_id,
        corpus_id="fixture-cti",
        membership=members,
        projections=(
            ProjectionSpec(backend="exact", enabled=True, required=True, fingerprint=writer.fingerprint),
            ProjectionSpec(backend="lexical", enabled=False, required=False, fingerprint="not-configured"),
            ProjectionSpec(backend="dense", enabled=False, required=False, fingerprint="not-configured"),
            ProjectionSpec(backend="graph", enabled=False, required=False, fingerprint="not-configured"),
        ),
        fingerprints={"exact": writer.fingerprint},
    )


def _scope_and_snapshot(manifest):
    policy = PublicFixturePolicy.trusted(
        corpus_id="fixture-cti", scope_id="public-fixture", source_allowlist=frozenset({"fixture-public"})
    )
    scope = policy.resolve_scope(
        Principal(principal_id="test", source="trusted_local_cli", capabilities=frozenset()), "fixture-cti"
    )
    snapshot = SnapshotRef(
        domain=manifest.domain,
        scope_id=manifest.scope_id,
        snapshot_id=manifest.generation_id,
        manifest_sha256=manifest.manifest_sha256,
    )
    return scope, snapshot


def test_valid_exact_id_and_source_id_are_persistent_snapshot_hits(tmp_path):
    batch, raw = _batch_and_raw_with_body_identifier()
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        store.persist_batch(batch, raw_payloads=raw)
        writer = ExactProjectionWriter(store, tmp_path / "indexes")
        manifest = _manifest(batch, writer)
        PublicationOrchestrator.trusted(store, [writer]).publish(manifest)
        scope, snapshot = _scope_and_snapshot(manifest)
        path = ExactIndex.path_for(
            tmp_path / "indexes", domain="cti", scope_id="public-fixture", generation_id=manifest.generation_id
        )
        index = ExactIndex.open(store, path=path)
        hits = index.lookup(
            ExternalIdentifier(namespace="cve", value="CVE-2026-999999", domain="cti"),
            scope=scope,
            snapshot=snapshot,
        )
        assert len(hits) == 1
        assert hits[0].metadata["match_kind"] == "external_identifier"
        source_hits = index.lookup(
            "source:fixture-public:fixture-cve-2026-999999", scope=scope, snapshot=snapshot
        )
        assert [hit.logical_uid for hit in source_hits] == [hits[0].logical_uid]


def test_body_mention_is_not_exact_identity_and_unknown_is_legitimate_miss(tmp_path):
    body_only = "CVE-2026-123456"
    batch, raw = _batch_and_raw_with_body_identifier(body_only)
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        store.persist_batch(batch, raw_payloads=raw)
        writer = ExactProjectionWriter(store, tmp_path / "indexes")
        manifest = _manifest(batch, writer)
        PublicationOrchestrator.trusted(store, [writer]).publish(manifest)
        scope, snapshot = _scope_and_snapshot(manifest)
        index = ExactIndex.open(
            store,
            path=ExactIndex.path_for(
                tmp_path / "indexes", domain="cti", scope_id="public-fixture", generation_id=manifest.generation_id
            ),
        )
        assert index.lookup(
            ExternalIdentifier(namespace="cve", value=body_only, domain="cti"),
            scope=scope,
            snapshot=snapshot,
        ) == ()


def test_exact_artifact_reopens_without_rebuilding(tmp_path):
    batch, raw = _batch_and_raw_with_body_identifier()
    db = tmp_path / "catalog.db"
    raw_root = tmp_path / "raw"
    index_root = tmp_path / "indexes"
    with EvidenceStore(db, raw_root) as store:
        store.persist_batch(batch, raw_payloads=raw)
        writer = ExactProjectionWriter(store, index_root)
        manifest = _manifest(batch, writer)
        PublicationOrchestrator.trusted(store, [writer]).publish(manifest)
        scope, snapshot = _scope_and_snapshot(manifest)
        path = ExactIndex.path_for(
            index_root, domain="cti", scope_id="public-fixture", generation_id=manifest.generation_id
        )
    with EvidenceStore(db, raw_root) as reopened:
        index = ExactIndex.open(reopened, path=path)
        hits = index.lookup(
            ExternalIdentifier(namespace="cve", value="CVE-2026-999999", domain="cti"),
            scope=scope,
            snapshot=snapshot,
        )
        assert len(hits) == 1
