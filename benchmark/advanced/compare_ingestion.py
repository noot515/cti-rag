"""CLI for Prompt 22 matched-corpus release-readiness comparison."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

import yaml

from benchmark.advanced.matched_config import file_sha256, load_config, resolve
from benchmark.advanced.matched_content import active_manifest, compare_content, direct_batch
from benchmark.advanced.matched_retrieval import compare_retrieval, measure_latency
from benchmark.advanced.release_readiness import compute_readiness, enriched_experiment, quality_evidence, restore_retained_generation
from packages.evidence.ids import canonical_json
from packages.evidence.store import EvidenceStore
from packages.integrations.opencti.sync import sync_once

REPORT_SCHEMA = "matched-corpus-comparison-v1"

def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def _state_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())

def run_comparison(config_path: Path | str, output: Path | str) -> dict[str, Any]:
    config_path, output = Path(config_path), Path(output); config = load_config(config_path); digest = file_sha256(resolve(config_path))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + digest[:10]; run_dir = output / run_id; state = run_dir / "state" / "i1-opencti"; run_dir.mkdir(parents=True, exist_ok=True)
    snapshot = yaml.safe_load(resolve(config_path).read_text(encoding="utf-8")); (run_dir / "config.snapshot.yaml").write_text(yaml.safe_dump(snapshot, sort_keys=True), encoding="utf-8")
    started = time.perf_counter(); capture, direct, tokenizer = direct_batch(config); direct_seconds = time.perf_counter() - started
    started = time.perf_counter(); sync = sync_once(config_path=resolve(config.opencti_config), environ={}, state_dir_override=state, reconcile=True); sync_wall = time.perf_counter() - started
    source_cfg = yaml.safe_load(resolve(config.opencti_config).read_text(encoding="utf-8")); ingested_source_instance = str((source_cfg.get("opencti") or {}).get("source_instance") or "unknown")
    with EvidenceStore(state / "catalog.db", state / "raw") as store:
        manifest = active_manifest(store, source_cfg); content, mapping = compare_content(direct, store, manifest); retrieval = compare_retrieval(direct, tokenizer, store, state, manifest, config); latency = measure_latency(store, state, manifest, config.queries, config)
    updates = [datetime.fromisoformat(str(r.payload.get("updated_at") or r.payload.get("modified")).replace("Z", "+00:00")) for r in capture.records if r.payload.get("updated_at") or r.payload.get("modified")]
    completed = datetime.fromisoformat(str(sync["capture_completed_at"]).replace("Z", "+00:00")); lag = None if not updates else max(0.0, (completed - max(updates)).total_seconds())
    quality = quality_evidence(config); rollback = {"status": config.release["rollback_mechanics"], "reason": "set to pass only after the focused retained-generation rollback test succeeds in the target validation chain", "production_restore_drill": "not_run"}
    readiness = compute_readiness(matched_content=content["status"], retrieval_parity=retrieval["status"], rollback_mechanics=rollback["status"], release_evidence=config.release, quality_gate=quality.get("noninferiority_gate", "not_run"), graph_gain_gate=quality.get("graph_gain_gate", "not_run"))
    report = {"schema_version": REPORT_SCHEMA, "run_id": run_id, "created_at": _now(), "config_sha256": digest,
        "comparison": {"experiment": "I1", "direct_label": config.direct_label, "ingestion_label": config.ingestion_label, "prompt17_context_c1_is_distinct": True, "matched_source": "sanitized recorded OpenCTI capture", "mapping_rule": mapping["mapping_rule"], "platform_attribution_permitted": content["status"] == "pass", "transport_provenance": {"direct_source_instance": config.direct_source_instance, "ingested_source_instance": ingested_source_instance, "treated_as_semantic_difference": False}},
        "canonical_content": content, "equivalence_mapping": {"sha256": mapping["sha256"], "entry_count": len(mapping["entries"]), "artifact": "equivalence-map.json"}, "retrieval": retrieval,
        "operational": {"direct": {"normalization_chunk_seconds": direct_seconds, "serialized_content_bytes": len(canonical_json(direct.model_dump(mode="json")).encode("utf-8"))}, "opencti_ingested": {"rebuild_seconds": sync["rebuild_seconds"], "wall_seconds": sync_wall, "state_bytes": _state_bytes(state), "retrieval_latency": latency, "ingestion_update_lag_seconds": lag, "checkpoint_states": sync["checkpoint_states"], "reconciliation": sync["reconciliation"], "network_used": sync["network_used"]}, "repeat_policy": {"cold_repeats": config.cold_repeats, "warm_repeats": config.warm_repeats, "concurrency": 1, "throughput_claim": False}},
        "quality": quality, "enriched_experiment": enriched_experiment(config.enriched_report), "release_evidence": config.release, "rollback": rollback, "readiness": readiness,
        "extraction": {"decision": "defer_extraction", "trigger": str(config.extraction.get("trigger") or "reconsider after CTI MVP-C, a materially different second domain, and documented duplication in at least two shared contract layers"), "second_domain_present": bool(config.extraction.get("second_domain"))},
        "legacy_default_changed": False, "automatic_promotion_performed": False}
    _write_json(run_dir / "equivalence-map.json", mapping); _write_json(run_dir / "comparison-report.json", report); _write_json(output / "latest.json", {"run_id": run_id, "report": f"{run_id}/comparison-report.json"})
    (run_dir / "comparison-report.md").write_text(f"# Matched-corpus release readiness\n\nDecision: **{readiness['overall'].upper()}**\n\nCanonical parity: {content['status']}  \nRetrieval parity: {retrieval['status']}  \nMVP-A: {readiness['MVP-A']['status']}  \nMVP-B: {readiness['MVP-B']['status']}  \nMVP-C: {readiness['MVP-C']['status']}\n", encoding="utf-8")
    return report

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare direct matched CTI content with OpenCTI-ingested content and emit a fail-closed release decision")
    parser.add_argument("--config", required=True, type=Path); parser.add_argument("--output", required=True, type=Path); args = parser.parse_args(argv)
    report = run_comparison(args.config, args.output); print(json.dumps({"run_id": report["run_id"], "decision": report["readiness"]["overall"], "canonical_content": report["canonical_content"]["status"], "retrieval": report["retrieval"]["status"]}, sort_keys=True)); return 0

if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["restore_retained_generation", "run_comparison"]
