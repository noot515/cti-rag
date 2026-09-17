from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from packages.domains.cti import CtiDomainAdapter
from packages.evidence.ids import canonical_hash, canonical_json
from packages.evidence.schema import SnapshotRef
from packages.indexing.manifests import GenerationManifest, GenerationMember, ProjectionReceipt, ProjectionSpec

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "cti" / "public_fixture.json"


def manifest_payload(*, name_suffix: str = "", revoked: bool = False):
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if name_suffix:
        value["objects"][0]["name"] += name_suffix
        value["source_snapshot_id"] += name_suffix.replace(" ", "-")
    if revoked:
        value["objects"][0]["revoked"] = True
    return value


def batch_and_raw(*, name_suffix: str = "", revoked: bool = False):
    payload = manifest_payload(name_suffix=name_suffix, revoked=revoked)
    batch = CtiDomainAdapter().normalize(payload)
    raw: dict[str, bytes] = {}
    for record in payload["objects"] + payload["relations"]:
        encoded = canonical_json(record).encode("utf-8")
        raw[sha256(encoded).hexdigest()] = encoded
    return batch, raw


def generation_manifest(batch, *, exact: bool = True, lexical: bool = True, dense: bool = False, graph: bool = False, corpus_id: str = "fixture-cti"):
    members = [
        GenerationMember(kind="object", evidence_uid=item.uid, revision_uid=item.revision_uid)
        for item in batch.objects
    ]
    members += [
        GenerationMember(kind="relation", evidence_uid=item.uid, revision_uid=item.revision_uid)
        for item in batch.relations
    ]
    members += [
        GenerationMember(kind="chunk", evidence_uid=item.uid, revision_uid=item.uid)
        for item in batch.chunks
    ]
    specs = (
        ProjectionSpec(backend="exact", enabled=exact, required=exact, fingerprint="exact-fixture-v1"),
        ProjectionSpec(backend="lexical", enabled=lexical, required=lexical, fingerprint="lexical-fixture-v1"),
        ProjectionSpec(backend="dense", enabled=dense, required=dense, fingerprint="dense-fixture-v1"),
        ProjectionSpec(backend="graph", enabled=graph, required=graph, fingerprint="graph-fixture-v1"),
    )
    return GenerationManifest.create(
        domain=batch.domain,
        scope_id=batch.scope_id,
        corpus_id=corpus_id,
        membership=members,
        projections=specs,
        fingerprints={"normalizer": "cti-normalizer-v2"},
    )


def snapshot_for(manifest: GenerationManifest):
    return SnapshotRef(
        domain=manifest.domain,
        scope_id=manifest.scope_id,
        snapshot_id=manifest.generation_id,
        manifest_sha256=manifest.manifest_sha256,
    )


class FakeProjectionWriter:
    def __init__(self, backend: str, *, store=None, fail_build: bool = False, visibility: bool = True, mutate: str | None = None):
        self.backend = backend
        self.store = store
        self.fail_build = fail_build
        self.visibility = visibility
        self.mutate = mutate
        self.build_calls = 0

    def build(self, manifest: GenerationManifest) -> ProjectionReceipt:
        self.build_calls += 1
        if self.store is not None:
            row = self.store.connection.execute(
                "SELECT status FROM projection_jobs WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=? AND backend=?",
                (manifest.domain, manifest.scope_id, manifest.corpus_id, manifest.generation_id, self.backend),
            ).fetchone()
            assert row is not None and row["status"] == "pending", "job must exist before projection write"
        if self.fail_build:
            raise RuntimeError(f"{self.backend} build failed")
        spec = next(item for item in manifest.enabled_projections if item.backend == self.backend)
        values = {
            "generation_id": manifest.generation_id,
            "domain": manifest.domain,
            "scope_id": manifest.scope_id,
            "corpus_id": manifest.corpus_id,
            "backend": self.backend,
            "manifest_sha256": manifest.manifest_sha256,
            "membership_sha256": manifest.membership_sha256,
            "member_count": len(manifest.membership),
            "fingerprint": spec.fingerprint,
            "artifact_sha256": canonical_hash(["fake-projection-v1", self.backend, manifest.manifest_sha256]),
            "visibility_verified": self.visibility,
            "sentinel": f"fake:{self.backend}:{manifest.generation_id[:12]}",
        }
        if self.mutate == "scope":
            values["scope_id"] = "wrong-scope"
        elif self.mutate == "manifest":
            values["manifest_sha256"] = "f" * 64
        elif self.mutate == "fingerprint":
            values["fingerprint"] = "wrong-model-v9"
        return ProjectionReceipt(**values)

    def verify(self, manifest: GenerationManifest, receipt: ProjectionReceipt) -> bool:
        return self.visibility
