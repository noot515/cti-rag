"""Trusted full-rebuild publication orchestrator."""
from __future__ import annotations

from packages.evidence.snapshot import SnapshotCatalog, SnapshotPublicationError


class PublicationDelayed(SnapshotPublicationError):
    pass


class InjectedPublicationCrash(RuntimeError):
    pass


class PublicationOrchestrator:
    _TOKEN = object()

    def __init__(self, store, writers, token):
        if token is not self._TOKEN:
            raise PermissionError("publication orchestrator requires trusted construction")
        self.store = store
        self.catalog = SnapshotCatalog(store)
        self.writers = {writer.backend: writer for writer in writers}

    @classmethod
    def trusted(cls, store, writers):
        return cls(store, writers, cls._TOKEN)

    def publish(self, manifest, *, crash_at=None):
        # Durable catalog/job state is established before any projection write.
        self.catalog.register_generation(manifest)
        active = self.catalog.active_generation(manifest.domain, manifest.scope_id, manifest.corpus_id)
        if active and active["generation_id"] == manifest.generation_id and self.catalog.state(manifest) == "active":
            self.catalog.acknowledge(manifest)
            return manifest.generation_id
        try:
            for spec in manifest.enabled_projections:
                row = self.store.connection.execute(
                    "SELECT status FROM projection_jobs WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=? AND backend=?",
                    (manifest.domain, manifest.scope_id, manifest.corpus_id, manifest.generation_id, spec.backend),
                ).fetchone()
                if row and row["status"] == "verified":
                    continue
                if crash_at == f"before_backend:{spec.backend}":
                    raise InjectedPublicationCrash(crash_at)
                writer = self.writers.get(spec.backend)
                if writer is None:
                    raise PublicationDelayed(f"projection writer unavailable: {spec.backend}")
                receipt = writer.build(manifest)
                if not writer.verify(manifest, receipt):
                    raise SnapshotPublicationError(f"projection verification failed: {spec.backend}")
                self.catalog.record_receipt(manifest, receipt)
                if crash_at == f"after_receipt:{spec.backend}":
                    raise InjectedPublicationCrash(crash_at)
            self.catalog.mark_ready(manifest)
            if crash_at == "after_ready":
                raise InjectedPublicationCrash(crash_at)
            self.catalog.activate(manifest)
            if crash_at == "after_activation":
                raise InjectedPublicationCrash(crash_at)
            self.catalog.acknowledge(manifest)
            return manifest.generation_id
        except (InjectedPublicationCrash, PublicationDelayed):
            raise
        except Exception as exc:
            self.catalog.fail(manifest, type(exc).__name__)
            raise

    def recover(self, domain, scope_id, corpus_id):
        return self.catalog.recover(domain, scope_id, corpus_id)
