"""Recoverable complete-scan OpenCTI ingestion through shared publication."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Mapping
from uuid import uuid4

from packages.domains.cti import CtiChunk, CtiDomainAdapter
from packages.evidence.config import load_advanced_rag_config
from packages.evidence.store import EvidenceStore, InjectedPersistenceFailure
from packages.indexing.chunker import ChunkingConfig, DeterministicTokenizer, chunk_objects
from packages.indexing.graph_indexer import CatalogGraphProjectionWriter
from packages.indexing.lexical_indexer import ExactProjectionWriter, LexicalProjectionWriter
from packages.indexing.manifests import GenerationManifest, GenerationMember, ProjectionSpec
from packages.indexing.orchestrator import (
    InjectedPublicationCrash,
    PublicationOrchestrator,
)

from .checkpoint import CheckpointKey, OpenCTICheckpointLedger
from .client import create_live_transport
from .normalizer import NORMALIZER_VERSION, normalize_complete_capture
from .reader import CAPTURE_KINDS, OpenCTIReader, RecordedOpenCTITransport


class OpenCTISyncError(RuntimeError):
    pass


class InjectedSyncCrash(RuntimeError):
    pass


def _generation_manifest(
    batch,
    *,
    corpus_id: str,
    exact_writer: ExactProjectionWriter,
    lexical_writer: LexicalProjectionWriter,
    graph_writer: CatalogGraphProjectionWriter,
    tokenizer: DeterministicTokenizer,
    chunk_config: ChunkingConfig,
) -> GenerationManifest:
    membership = [
        GenerationMember(kind="object", evidence_uid=item.uid, revision_uid=item.revision_uid)
        for item in batch.objects
    ]
    membership.extend(
        GenerationMember(kind="relation", evidence_uid=item.uid, revision_uid=item.revision_uid)
        for item in batch.relations
    )
    membership.extend(
        GenerationMember(kind="chunk", evidence_uid=item.uid, revision_uid=item.uid)
        for item in batch.chunks
    )
    projections = (
        ProjectionSpec(
            backend="exact", enabled=True, required=True, fingerprint=exact_writer.fingerprint
        ),
        ProjectionSpec(
            backend="lexical", enabled=True, required=True, fingerprint=lexical_writer.fingerprint
        ),
        ProjectionSpec(
            backend="graph", enabled=True, required=True, fingerprint=graph_writer.fingerprint
        ),
    )
    return GenerationManifest.create(
        domain=batch.domain,
        scope_id=batch.scope_id,
        corpus_id=corpus_id,
        membership=membership,
        projections=projections,
        fingerprints={
            "normalizer": NORMALIZER_VERSION,
            "chunker": chunk_config.fingerprint,
            "tokenizer": tokenizer.fingerprint,
            "exact": exact_writer.fingerprint,
            "lexical": lexical_writer.fingerprint,
            "graph": graph_writer.fingerprint,
        },
    )


def _checkpoint_keys(config) -> tuple[CheckpointKey, ...]:
    return tuple(
        CheckpointKey.create(
            source_instance=config.opencti.source_instance,
            domain="cti",
            scope_id=config.source.scope_id,
            supported_type=kind,
            filters={},
        )
        for kind in CAPTURE_KINDS
    )


def sync_once(
    *,
    config_path: Path,
    environ: Mapping[str, str] | None = None,
    state_dir_override: Path | None = None,
    crash_at: str | None = None,
) -> dict[str, Any]:
    """Capture once, rebuild a full generation, and advance publication checkpoints.

    Delivery is deliberately at-least-once. A restart after an interrupted scan
    performs a bounded full rescan; the page ledger prevents cursor advancement
    past an unpersisted page, while immutable evidence IDs make replay idempotent.
    """
    config = load_advanced_rag_config(config_path, environ=environ)
    if config.profile != "opencti" or not config.opencti.enabled:
        raise OpenCTISyncError("OpenCTI sync requires the explicit opencti profile")
    if config.opencti.live_serving_enabled:
        raise OpenCTISyncError(
            "maintained OpenCTI serving is disabled until visibility reconciliation"
        )

    repo_root = Path(__file__).resolve().parents[3]
    state_dir = state_dir_override or Path(config.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = state_dir / "catalog.db"
    raw_root = state_dir / "raw"
    index_root = state_dir / "indexes"

    if config.opencti.mode == "fixture":
        fixture_path = Path(config.opencti.recorded_fixture)
        if not fixture_path.is_absolute():
            fixture_path = repo_root / fixture_path
        transport = RecordedOpenCTITransport.from_path(fixture_path)
        if transport.platform_version != config.opencti.expected_platform_version:
            raise OpenCTISyncError(
                "recorded OpenCTI fixture platform version differs from pinned matrix"
            )
        source_uri = f"recorded://{Path(config.opencti.recorded_fixture).as_posix()}"
        sanitized = True
    else:
        transport = create_live_transport(config.opencti, environ=environ)
        source_uri = config.opencti.api_url
        sanitized = False

    reader = OpenCTIReader(
        transport,
        source_instance=config.opencti.source_instance,
        page_size=config.opencti.page_size,
        timeout_seconds=config.opencti.timeout_seconds,
        max_retries=config.opencti.max_retries,
        max_pages_per_kind=config.opencti.max_pages_per_kind,
    )
    keys = _checkpoint_keys(config)
    key_by_kind = {key.supported_type: key for key in keys}
    run_id = uuid4().hex
    rebuild_started = time.monotonic()

    with EvidenceStore(catalog_path, raw_root) as store:
        ledger = OpenCTICheckpointLedger(store)
        recovered_publications = ledger.reconcile_activated(
            corpus_id=config.source.corpus_id
        )
        scan_bounds = {
            "mode": "full_rescan",
            "lookback_role": "dedup_only",
            "source_version": str(transport.platform_version),
        }
        for key in keys:
            ledger.begin_run(
                key,
                run_id=run_id,
                source_version=str(transport.platform_version),
                scan_bounds=scan_bounds,
            )

        def record_page(page):
            ledger.record_page(
                key_by_kind[page.kind],
                run_id=run_id,
                page=page,
            )

        try:
            capture = reader.scan_complete(page_callback=record_page)
        except Exception as exc:
            ledger.fail_run(
                keys,
                run_id=run_id,
                error_code=type(exc).__name__,
            )
            raise

        if not capture.complete:
            ledger.fail_run(keys, run_id=run_id, error_code="partial-capture")
            raise OpenCTISyncError("partial OpenCTI scan cannot publish")

        final_bounds = {
            **scan_bounds,
            "capture_started_at": capture.capture_started_at,
            "capture_completed_at": capture.capture_completed_at,
            "page_count": len(capture.pages),
        }
        for key in keys:
            ledger.mark_capture_complete(
                key,
                run_id=run_id,
                scan_bounds=final_bounds,
            )

        normalized = normalize_complete_capture(
            capture,
            scope_id=config.source.scope_id,
            source_uri=source_uri,
            sanitized_public_fixture=sanitized,
        )
        adapter = CtiDomainAdapter()
        tokenizer = DeterministicTokenizer()
        chunk_config = ChunkingConfig(target_tokens=450, overlap_tokens=75)
        chunks = chunk_objects(
            normalized.batch.objects,
            serialization_hints=adapter.field_serialization_hints(),
            tokenizer=tokenizer,
            config=chunk_config,
            chunk_class=CtiChunk,
        )
        batch = normalized.batch.model_copy(update={"chunks": chunks})

        try:
            persisted = store.persist_batch(
                batch,
                raw_payloads=normalized.raw_payloads,
                fail_after_raw=crash_at == "after_raw",
            )
        except InjectedPersistenceFailure:
            ledger.fail_run(keys, run_id=run_id, error_code="after_raw")
            raise
        if crash_at == "after_catalog":
            ledger.fail_run(keys, run_id=run_id, error_code="after_catalog")
            raise InjectedSyncCrash("after_catalog")

        exact_writer = ExactProjectionWriter(store, index_root)
        lexical_writer = LexicalProjectionWriter(store, index_root, tokenizer=tokenizer)
        graph_writer = CatalogGraphProjectionWriter(store)
        generation = _generation_manifest(
            batch,
            corpus_id=config.source.corpus_id,
            exact_writer=exact_writer,
            lexical_writer=lexical_writer,
            graph_writer=graph_writer,
            tokenizer=tokenizer,
            chunk_config=chunk_config,
        )
        ledger.bind_generation(
            keys,
            run_id=run_id,
            generation_id=generation.generation_id,
        )
        publisher = PublicationOrchestrator.trusted(
            store, [exact_writer, lexical_writer, graph_writer]
        )
        try:
            publisher.publish(generation, crash_at=crash_at)
        except InjectedPublicationCrash:
            # Leave the publication checkpoint unadvanced. On restart,
            # reconcile_activated() repairs activation-before-checkpoint.
            raise
        except Exception as exc:
            ledger.fail_run(
                keys,
                run_id=run_id,
                error_code=type(exc).__name__,
            )
            raise

        active = store.connection.execute(
            "SELECT generation_id,manifest_sha256 FROM active_generations "
            "WHERE domain=? AND scope_id=? AND corpus_id=?",
            (batch.domain, batch.scope_id, config.source.corpus_id),
        ).fetchone()
        if active is None or active["generation_id"] != generation.generation_id:
            ledger.fail_run(
                keys,
                run_id=run_id,
                error_code="active-generation-mismatch",
            )
            raise OpenCTISyncError(
                "complete scan published without expected active generation"
            )
        ledger.mark_published(
            keys,
            run_id=run_id,
            generation_id=generation.generation_id,
            corpus_id=config.source.corpus_id,
        )
        if crash_at == "after_published_checkpoint":
            raise InjectedSyncCrash("after_published_checkpoint")

        checkpoints = {
            key.supported_type: ledger.get(key)
            for key in keys
        }

    rebuild_seconds = max(0.0, time.monotonic() - rebuild_started)
    return {
        "schema_version": "opencti-sync-report-v2",
        "delivery_semantics": "at-least-once",
        "incremental_projection_reuse": False,
        "rebuild_mode": "full-fresh-generation",
        "rebuild_seconds": rebuild_seconds,
        "mode": config.opencti.mode,
        "source_instance": config.opencti.source_instance,
        "platform_version": capture.platform_version,
        "client_version": (
            config.opencti.expected_client_version
            if config.opencti.mode == "live"
            else "not_loaded"
        ),
        "capture_started_at": capture.capture_started_at,
        "capture_completed_at": capture.capture_completed_at,
        "capture_complete": capture.complete,
        "upstream_point_in_time_snapshot_claim": False,
        "consistency_warnings": list(capture.consistency_warnings),
        "duplicate_records": capture.duplicate_records,
        "objects": len(batch.objects),
        "relations": len(batch.relations),
        "chunks": len(batch.chunks),
        "quarantine_counts": dict(normalized.quarantine_counts),
        "logical_changes": persisted.logical_changes,
        "generation_id": generation.generation_id,
        "manifest_sha256": generation.manifest_sha256,
        "required_projections": ["exact", "lexical", "graph"],
        "network_used": config.opencti.mode == "live",
        "live_maintained_serving": False,
        "raw_sensitive_payloads_logged": False,
        "recovered_publication_checkpoints": recovered_publications,
        "checkpoint_states": {
            kind: None if state is None else state.state
            for kind, state in checkpoints.items()
        },
        "ingestion_cursors_distinct_from_published": True,
    }


__all__ = ["InjectedSyncCrash", "OpenCTISyncError", "sync_once"]
