"""Coherent staged publication over an atomic catalog pointer."""
from __future__ import annotations
from datetime import datetime, timezone
from .models import SnapshotManifest

class PublicationError(RuntimeError): pass

class SnapshotPublisher:
    def __init__(self,catalog): self.catalog=catalog
    def stage_generation(self,generation):
        return self.catalog.stage_generation(generation)
    def publish(self,generation_ids,required_kinds,created_at=None,failpoint=None):
        generations=tuple(self.catalog.get_generation(gid) for gid in generation_ids)
        if any(g is None for g in generations): raise PublicationError("missing staged generation")
        kinds={g.kind for g in generations}
        missing=set(required_kinds)-kinds
        if missing: raise PublicationError("missing required projections: "+",".join(sorted(missing)))
        for g in generations:
            if not g.ready: raise PublicationError(f"projection not ready: {g.kind}")
            if not g.visible: raise PublicationError(f"projection not serving-visible: {g.kind}")
            if not g.referential_integrity: raise PublicationError(f"projection referential integrity failed: {g.kind}")
        revision_sets={g.revision_set_digest for g in generations}
        if len(revision_sets)!=1: raise PublicationError("projection revision sets are incompatible")
        candidate=SnapshotManifest.build(tuple(sorted(generations,key=lambda g:g.kind)),created_at or datetime.now(timezone.utc))
        existing=self.catalog.get_manifest(candidate.manifest_id)
        manifest=existing or candidate
        if existing is None:self.catalog.store_manifest(manifest)
        if failpoint=="before_pointer_swap": raise PublicationError("failpoint:before_pointer_swap")
        self.catalog.publish_pointer(manifest.manifest_id)
        return manifest
    def rollback(self,manifest_id):
        manifest=self.catalog.get_manifest(manifest_id)
        if manifest is None: raise PublicationError("rollback manifest not found")
        for binding in manifest.projections:
            generation=self.catalog.get_generation(binding.generation_id)
            if generation is None or not (generation.ready and generation.visible and generation.referential_integrity):
                raise PublicationError("rollback generation is not serviceable")
        self.catalog.publish_pointer(manifest_id)
        return manifest
    def cleanup_failed(self,generation_id,builder):
        if self.catalog.generation_status(generation_id)!="failed": return False
        if self.catalog.generation_in_use(generation_id): return False
        builder.cleanup(generation_id)
        return self.catalog.cleanup_failed_generation(generation_id)
