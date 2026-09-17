"""Offline trusted CLI for deterministic fixture ingestion and publication."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from typing import Any

from packages.domains.cti import CtiDomainAdapter, CtiChunk
from packages.domains.cti.normalize import load_cti_corpus_fixture
from packages.evidence.config import load_advanced_rag_config
from packages.evidence.ids import canonical_json
from packages.evidence.policy import Principal, PublicFixturePolicy
from packages.evidence.store import EvidenceStore

from .chunker import ChunkingConfig, DeterministicTokenizer, chunk_objects
from .lexical_indexer import ExactProjectionWriter, LexicalProjectionWriter
from .manifests import GenerationManifest, GenerationMember, ProjectionSpec
from .orchestrator import PublicationOrchestrator


class IngestionError(RuntimeError):
    pass


def _fixture_manifest_path(path: Path) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    fixture_root = (repo_root / "tests" / "fixtures" / "cti").resolve()
    candidate = path.resolve()
    try:
        candidate.relative_to(fixture_root)
    except ValueError as exc:
        raise IngestionError("fixture profile only accepts manifests under tests/fixtures/cti") from exc
    if not candidate.is_file():
        raise IngestionError(f"fixture manifest does not exist: {candidate}")
    return candidate


def _read_fixture_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestionError("fixture corpus manifest is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "cti-corpus-manifest-v1":
        raise IngestionError("fixture ingest requires cti-corpus-manifest-v1")
    for forbidden in ("queries_file", "qrels_file", "annotations_file", "ground_truth", "answers"):
        if forbidden in payload:
            raise IngestionError(f"evaluation-only role is forbidden in corpus manifest: {forbidden}")
    if not isinstance(payload.get("objects_file"), str) or not isinstance(payload.get("objects_sha256"), str):
        raise IngestionError("fixture corpus manifest must declare objects_file and objects_sha256")
    return payload


def _raw_payloads_for_fixture(manifest_path: Path, manifest_payload: dict[str, Any], batch: Any) -> dict[str, bytes]:
    relative = str(manifest_payload["objects_file"])
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or "." in posix.parts or "\\" in relative:
        raise IngestionError("objects_file must be a normalized relative POSIX path")
    objects_path = (manifest_path.parent / relative).resolve()
    try:
        objects_path.relative_to(manifest_path.parent.resolve())
    except ValueError as exc:
        raise IngestionError("objects_file escapes fixture root") from exc
    if sha256(objects_path.read_bytes()).hexdigest() != manifest_payload["objects_sha256"]:
        raise IngestionError("objects_file hash does not match fixture manifest")

    candidates: dict[str, bytes] = {}
    for line in objects_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("schema_version") != "cti-object-record-v1":
            raise IngestionError("unexpected object record schema")
        normalized = {key: value for key, value in record.items() if key != "schema_version"}
        raw = canonical_json(normalized).encode("utf-8")
        candidates[sha256(raw).hexdigest()] = raw

    for relation in manifest_payload.get("relations", []):
        raw = canonical_json(relation).encode("utf-8")
        candidates[sha256(raw).hexdigest()] = raw

    source_id_by_uid = {obj.uid: obj.source_refs[0].source_object_id for obj in batch.objects if obj.source_refs}
    for relation in batch.relations:
        if relation.assertion_kind != "embedded_reference":
            continue
        source_id = source_id_by_uid.get(relation.source_object_uid)
        target_id = source_id_by_uid.get(relation.target_object_uid)
        if not source_id or not target_id or not relation.source_field_path:
            raise IngestionError("embedded reference lacks source identity needed for raw provenance")
        record = {
            "source_record_id": source_id,
            "source_object_id": source_id,
            "target_object_id": target_id,
            "original_relation": "object_refs",
            "normalized_relation": "references",
            "assertion_kind": "embedded_reference",
            "source_field_path": relation.source_field_path,
        }
        raw = canonical_json(record).encode("utf-8")
        candidates[sha256(raw).hexdigest()] = raw

    required: set[str] = set()
    for value in (*batch.objects, *batch.relations, *batch.chunks):
        refs = value.source_refs if hasattr(value, "source_refs") else value.evidence_refs
        required.update(ref.raw_payload_sha256 for ref in refs)
    missing = sorted(required - set(candidates))
    if missing:
        raise IngestionError(f"cannot reconstruct raw fixture payload for digest {missing[0]}")
    return {digest: candidates[digest] for digest in sorted(required)}


def _generation_manifest(
    batch,
    *,
    corpus_id: str,
    exact_writer: ExactProjectionWriter,
    lexical_writer: LexicalProjectionWriter,
    tokenizer: DeterministicTokenizer,
    chunk_config: ChunkingConfig,
) -> GenerationManifest:
    membership = [GenerationMember(kind="object", evidence_uid=item.uid, revision_uid=item.revision_uid) for item in batch.objects]
    membership.extend(GenerationMember(kind="relation", evidence_uid=item.uid, revision_uid=item.revision_uid) for item in batch.relations)
    membership.extend(GenerationMember(kind="chunk", evidence_uid=item.uid, revision_uid=item.uid) for item in batch.chunks)
    projections = (
        ProjectionSpec(backend="exact", enabled=True, required=True, fingerprint=exact_writer.fingerprint),
        ProjectionSpec(backend="lexical", enabled=True, required=True, fingerprint=lexical_writer.fingerprint),
        ProjectionSpec(backend="dense", enabled=False, required=False, fingerprint="not-configured"),
        ProjectionSpec(backend="graph", enabled=False, required=False, fingerprint="not-configured"),
    )
    return GenerationManifest.create(
        domain=batch.domain,
        scope_id=batch.scope_id,
        corpus_id=corpus_id,
        membership=membership,
        projections=projections,
        fingerprints={
            "normalizer": "cti-normalizer-v2",
            "chunker": chunk_config.fingerprint,
            "tokenizer": tokenizer.fingerprint,
            "exact": exact_writer.fingerprint,
            "lexical": lexical_writer.fingerprint,
            "dense": "not-configured",
            "graph": "not-configured",
        },
    )


def ingest_fixture(*, config_path: Path, manifest_path: Path) -> dict[str, Any]:
    config = load_advanced_rag_config(config_path)
    if config.profile != "fixture":
        raise IngestionError("Prompt 07 CLI currently supports fixture profile only")
    if not config.channels.exact_enabled or not config.channels.lexical_enabled:
        raise IngestionError("fixture ingestion requires exact and lexical channels")
    if config.channels.dense_enabled or config.channels.graph_enabled:
        raise IngestionError("fixture Prompt 07 profile must record dense and graph as not configured")
    if config.network.allow_outbound or config.network.allow_downloads or config.network.web_search:
        raise IngestionError("fixture ingestion must remain offline")

    manifest_path = _fixture_manifest_path(manifest_path)
    manifest_payload = _read_fixture_manifest(manifest_path)
    principal = Principal(principal_id="advanced-fixture-cli", source="trusted_local_cli", capabilities=frozenset({"index:fixture"}))
    policy = PublicFixturePolicy.trusted(
        corpus_id=config.source.corpus_id,
        scope_id=config.source.scope_id,
        source_allowlist=frozenset(config.source.source_allowlist),
    )
    scope = policy.resolve_scope(principal, config.source.corpus_id)

    adapter = CtiDomainAdapter()
    batch = load_cti_corpus_fixture(manifest_path)
    if batch.domain != scope.domain or batch.scope_id != scope.scope_id:
        raise IngestionError("normalized fixture does not match resolved trusted scope")
    source_instances = {ref.source_instance for obj in batch.objects for ref in obj.source_refs}
    if not source_instances or not source_instances.issubset(scope.source_allowlist):
        raise IngestionError("fixture source is not on the resolved source allowlist")

    tokenizer = DeterministicTokenizer()
    chunk_config = ChunkingConfig(target_tokens=450, overlap_tokens=75)
    chunks = chunk_objects(
        batch.objects,
        serialization_hints=adapter.field_serialization_hints(),
        tokenizer=tokenizer,
        config=chunk_config,
        chunk_class=CtiChunk,
    )
    batch = batch.model_copy(update={"chunks": chunks})
    raw_payloads = _raw_payloads_for_fixture(manifest_path, manifest_payload, batch)

    state_dir = Path(config.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = state_dir / "catalog.db"
    raw_root = state_dir / "raw"
    index_root = state_dir / "indexes"

    with EvidenceStore(catalog_path, raw_root) as store:
        persist = store.persist_batch(batch, raw_payloads=raw_payloads)
        exact_writer = ExactProjectionWriter(store, index_root)
        lexical_writer = LexicalProjectionWriter(store, index_root, tokenizer=tokenizer, k1=1.5, b=0.75)
        generation = _generation_manifest(
            batch,
            corpus_id=config.source.corpus_id,
            exact_writer=exact_writer,
            lexical_writer=lexical_writer,
            tokenizer=tokenizer,
            chunk_config=chunk_config,
        )
        PublicationOrchestrator.trusted(store, [exact_writer, lexical_writer]).publish(generation)
        active = store.connection.execute(
            "SELECT generation_id,manifest_sha256 FROM active_generations WHERE domain=? AND scope_id=? AND corpus_id=?",
            (batch.domain, batch.scope_id, config.source.corpus_id),
        ).fetchone()
        if active is None or active["generation_id"] != generation.generation_id or active["manifest_sha256"] != generation.manifest_sha256:
            raise IngestionError("publication completed without the expected active pointer")
        return {
            "schema_version": "fixture-ingest-report-v1",
            "generation_id": generation.generation_id,
            "manifest_sha256": generation.manifest_sha256,
            "objects": len(batch.objects),
            "relations": len(batch.relations),
            "chunks": len(batch.chunks),
            "logical_changes": persist.logical_changes,
            "required_projections": [item.backend for item in generation.enabled_projections if item.required],
            "dense": "not_configured",
            "graph": "not_configured",
            "network_used": False,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Advanced offline indexing CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="ingest and publish a trusted fixture corpus")
    ingest.add_argument("--config", required=True, type=Path)
    ingest.add_argument("--manifest", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "ingest":
        report = ingest_fixture(config_path=args.config, manifest_path=args.manifest)
        print(json.dumps(report, sort_keys=True))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
