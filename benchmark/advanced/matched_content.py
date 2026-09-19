"""Canonical content parity using explicit provenance equivalence only."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping
import yaml
from benchmark.advanced.matched_config import MatchedConfig, MatchedCorpusError, resolve
from packages.domains.cti import CtiChunk, CtiDomainAdapter
from packages.evidence.ids import canonical_hash, canonical_json
from packages.evidence.snapshot import SnapshotCatalog
from packages.evidence.store import EvidenceStore
from packages.indexing.chunker import ChunkingConfig, DeterministicTokenizer, chunk_objects
from packages.integrations.opencti.normalizer import normalize_complete_capture
from packages.integrations.opencti.reader import OpenCTIReader, RecordedOpenCTITransport

def direct_batch(config: MatchedConfig):
    source_cfg = yaml.safe_load(resolve(config.opencti_config).read_text(encoding="utf-8")); oc = source_cfg["opencti"]; fixture = resolve(Path(str(oc["recorded_fixture"])))
    reader = OpenCTIReader(RecordedOpenCTITransport.from_path(fixture), source_instance=config.direct_source_instance, page_size=int(oc.get("page_size", 100)), timeout_seconds=float(oc.get("timeout_seconds", 30)), max_retries=int(oc.get("max_retries", 2)), max_pages_per_kind=int(oc.get("max_pages_per_kind", 10000)))
    capture = reader.scan_complete(); normalized = normalize_complete_capture(capture, scope_id=config.direct_scope_id, source_uri=f"direct-recorded://{fixture.name}", sanitized_public_fixture=True); tokenizer = DeterministicTokenizer()
    chunks = chunk_objects(normalized.batch.objects, serialization_hints=CtiDomainAdapter().field_serialization_hints(), tokenizer=tokenizer, config=ChunkingConfig(450, 75), chunk_class=CtiChunk)
    return capture, normalized.batch.model_copy(update={"chunks": chunks}), tokenizer

def active_manifest(store: EvidenceStore, source_cfg: Mapping[str, Any]):
    source, catalog = source_cfg["source"], SnapshotCatalog(store); active = catalog.active_generation("cti", str(source["scope_id"]), str(source["corpus_id"]))
    if active is None: raise MatchedCorpusError("I1 has no active generation")
    manifest = catalog.load_manifest("cti", str(source["scope_id"]), str(source["corpus_id"]), active["generation_id"])
    if manifest is None: raise MatchedCorpusError("I1 active generation manifest is unavailable")
    return manifest

def _store_rows(store, manifest, kind):
    rows = []
    for member in manifest.membership:
        if member.kind != kind: continue
        row = store.get_chunk(manifest.domain, manifest.scope_id, member.evidence_uid) if kind == "chunk" else store.get_revision(manifest.domain, manifest.scope_id, member.revision_uid)
        if row is None: raise MatchedCorpusError(f"missing {kind} generation member")
        rows.append({"uid": member.evidence_uid, "revision_uid": member.revision_uid, "payload": row["payload"], "sources": row["sources"]})
    return rows

def _direct_rows(batch, kind):
    items, refs_name = (batch.objects, "source_refs") if kind == "object" else (batch.relations, "evidence_refs"); rows = []
    for item in items:
        exclude = {refs_name} | ({"raw_payload_ref"} if kind == "object" else set()); rows.append({"uid": item.uid, "revision_uid": item.revision_uid, "payload": item.model_dump(mode="json", exclude=exclude), "sources": [{"source_instance": r.source_instance, "source_object_id": r.source_object_id, "raw_sha256": r.raw_payload_sha256} for r in getattr(item, refs_name)]})
    return rows

def _key(row, kind):
    if len(row["sources"]) != 1: raise MatchedCorpusError("matched fixture requires one explicit source per member")
    source = row["sources"][0]; digest = source.get("raw_sha256") or source.get("raw_payload_sha256")
    if not digest: raise MatchedCorpusError("matched member lacks raw provenance hash")
    return kind, str(source["source_object_id"]), str(digest)

def _normalize_policy(payload):
    out = dict(payload); policy = out.get("policy")
    if isinstance(policy, Mapping): policy = dict(policy); policy["source_instances"] = ["<matched-source>"] if policy.get("source_instances") else []; out["policy"] = policy
    return out

def object_semantics(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _normalize_policy({k: v for k, v in payload.items() if k not in {"uid", "revision_uid", "scope_id"}})

def _relation_semantics(payload, uid_map):
    out = _normalize_policy({k: v for k, v in payload.items() if k not in {"uid", "revision_uid", "scope_id", "source_object_uid", "target_object_uid"}}); out["source_endpoint"] = uid_map.get(str(payload["source_object_uid"])); out["target_endpoint"] = uid_map.get(str(payload["target_object_uid"])); return out

def compare_content(batch, store: EvidenceStore, manifest):
    dobj, iobj, drel, irel = _direct_rows(batch, "object"), _store_rows(store, manifest, "object"), _direct_rows(batch, "relation"), _store_rows(store, manifest, "relation")
    db, ib, dr, ir = {_key(x, "object"): x for x in dobj}, {_key(x, "object"): x for x in iobj}, {_key(x, "relation"): x for x in drel}, {_key(x, "relation"): x for x in irel}; mismatches, entries, duid, iuid = [], [], {}, {}
    for key in sorted(set(db) | set(ib)):
        left, right = db.get(key), ib.get(key)
        if left is None or right is None: mismatches.append({"kind": "object-membership", "key": list(key)}); continue
        duid[left["uid"]], iuid[right["uid"]] = key[1], key[1]; entries.append({"kind": "object", "source_object_id": key[1], "raw_sha256": key[2], "direct_uid": left["uid"], "ingested_uid": right["uid"], "direct_source_instance": left["sources"][0]["source_instance"], "ingested_source_instance": right["sources"][0]["source_instance"], "basis": "source_object_id+raw_sha256"})
        if canonical_json(object_semantics(left["payload"])) != canonical_json(object_semantics(right["payload"])): mismatches.append({"kind": "object-semantic", "source_object_id": key[1]})
    for key in sorted(set(dr) | set(ir)):
        left, right = dr.get(key), ir.get(key)
        if left is None or right is None: mismatches.append({"kind": "relation-membership", "key": list(key)}); continue
        entries.append({"kind": "relation", "source_object_id": key[1], "raw_sha256": key[2], "direct_uid": left["uid"], "ingested_uid": right["uid"], "direct_source_instance": left["sources"][0]["source_instance"], "ingested_source_instance": right["sources"][0]["source_instance"], "basis": "source_object_id+raw_sha256"})
        if canonical_json(_relation_semantics(left["payload"], duid)) != canonical_json(_relation_semantics(right["payload"], iuid)): mismatches.append({"kind": "relation-semantic", "source_object_id": key[1]})
    dchunks = {(duid.get(c.object_uid), c.section_path, c.ordinal, c.content_hash): _normalize_policy(c.model_dump(mode="json", exclude={"uid", "object_uid", "object_revision_uid", "scope_id", "source_refs"})) for c in batch.chunks}; ichunks = {}
    for row in _store_rows(store, manifest, "chunk"):
        p = row["payload"]; key = (iuid.get(str(p["object_uid"])), str(p["section_path"]), int(p["ordinal"]), str(p["content_hash"])); ichunks[key] = _normalize_policy({k: v for k, v in p.items() if k not in {"uid", "object_uid", "object_revision_uid", "scope_id"}})
    for key in sorted(set(dchunks) | set(ichunks)):
        if key not in dchunks or key not in ichunks or canonical_json(dchunks.get(key)) != canonical_json(ichunks.get(key)): mismatches.append({"kind": "chunk-semantic", "key": list(key)})
    mapping = {"schema_version": "matched-provenance-equivalence-v1", "mapping_rule": "kind + source_object_id + raw_sha256; never name matching", "entries": entries}; mapping["sha256"] = canonical_hash([mapping["schema_version"], entries])
    return {"status": "pass" if not mismatches else "fail", "objects": [len(dobj), len(iobj)], "relations": [len(drel), len(irel)], "chunks": [len(dchunks), len(ichunks)], "mismatch_count": len(mismatches), "mismatches": mismatches, "transport_provenance_is_separate": True, "transport_provenance_difference_fields": ["source_instance", "scope_id", "local_uid"], "markings_are_semantic": True}, mapping

__all__ = ["active_manifest", "compare_content", "direct_batch", "object_semantics"]
