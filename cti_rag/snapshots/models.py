"""Immutable projection-generation, snapshot-manifest, and reader-lease models."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Tuple
from cti_rag.contracts import SnapshotManifestRef, ensure_utc, namespaced_uid, sha256_hex

@dataclass(frozen=True)
class ProjectionPayload:
    payload_uid: str
    revision_uid: str
    locator_json: str
    text_digest: str
    original_text: str = ""
    def __post_init__(self):
        if not self.payload_uid.strip() or not self.revision_uid.strip() or not self.locator_json.strip() or not self.text_digest.strip():
            raise ValueError("projection payload identity/provenance fields required")

@dataclass(frozen=True)
class ProjectionGeneration:
    generation_id: str
    kind: str
    revision_uids: Tuple[str,...]
    representation_versions: Tuple[str,...]
    checksum: str
    ready: bool
    visible: bool
    referential_integrity: bool
    quarantined_count: int
    supported_query_capabilities: Tuple[str,...]
    created_at: datetime
    payloads: Tuple[ProjectionPayload,...] = ()
    def __post_init__(self):
        ensure_utc(self.created_at)
        if not self.generation_id.strip() or not self.kind.strip() or not self.checksum.strip(): raise ValueError("generation identity fields required")
        if tuple(sorted(set(self.revision_uids))) != tuple(self.revision_uids): raise ValueError("revision_uids must be sorted and unique")
        if self.quarantined_count < 0: raise ValueError("quarantined_count cannot be negative")
        allowed=set(self.revision_uids)
        if any(p.revision_uid not in allowed for p in self.payloads): raise ValueError("payload revision must belong to generation revision set")
    @property
    def revision_set_digest(self):
        return sha256_hex({"revision_uids": self.revision_uids})

@dataclass(frozen=True)
class ProjectionBinding:
    kind: str
    generation_id: str
    checksum: str
    representation_versions: Tuple[str,...]
    supported_query_capabilities: Tuple[str,...]

@dataclass(frozen=True)
class SnapshotManifest:
    manifest_id: str
    corpus_digest: str
    revision_uids: Tuple[str,...]
    projections: Tuple[ProjectionBinding,...]
    quarantined_count: int
    supported_query_capabilities: Tuple[str,...]
    created_at: datetime
    schema_version: str = "snapshot-manifest/2"
    def __post_init__(self):
        ensure_utc(self.created_at)
        if not self.manifest_id.strip() or not self.corpus_digest.strip() or not self.projections: raise ValueError("snapshot manifest fields required")
        if tuple(sorted(set(self.revision_uids))) != tuple(self.revision_uids): raise ValueError("manifest revision_uids must be sorted and unique")
        if len({p.kind for p in self.projections}) != len(self.projections): raise ValueError("one generation per projection kind is allowed")
    @classmethod
    def build(cls, generations: Tuple[ProjectionGeneration,...], created_at: datetime):
        if not generations: raise ValueError("at least one projection generation is required")
        revision_uids=generations[0].revision_uids
        if any(g.revision_uids != revision_uids for g in generations): raise ValueError("projection generations do not share an identical revision set")
        bindings=tuple(sorted((ProjectionBinding(g.kind,g.generation_id,g.checksum,g.representation_versions,g.supported_query_capabilities) for g in generations),key=lambda x:x.kind))
        corpus_digest=sha256_hex({"revision_uids":revision_uids})
        capabilities=tuple(sorted({c for g in generations for c in g.supported_query_capabilities}))
        quarantined=max(g.quarantined_count for g in generations)
        identity={"corpus_digest":corpus_digest,"revision_uids":revision_uids,"projections":bindings,"quarantined_count":quarantined,"capabilities":capabilities}
        return cls(namespaced_uid("man","snapshot.manifest",identity),corpus_digest,revision_uids,bindings,quarantined,capabilities,created_at)
    def to_ref(self):
        return SnapshotManifestRef(self.manifest_id,self.corpus_digest,self.created_at,tuple(p.generation_id for p in self.projections))
    def generation_id(self,kind:str):
        for p in self.projections:
            if p.kind==kind: return p.generation_id
        return None

@dataclass(frozen=True)
class PinnedSnapshot:
    manifest: SnapshotManifest
    lease_id: str
    expires_at: datetime
    def __post_init__(self): ensure_utc(self.expires_at)
