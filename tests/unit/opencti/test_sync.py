from __future__ import annotations

from pathlib import Path

from packages.evidence.store import EvidenceStore
from packages.integrations.opencti.sync import sync_once


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "benchmark" / "advanced" / "configs" / "opencti.yaml"


def test_sanitized_complete_scan_publishes_normal_generation(tmp_path: Path):
    report = sync_once(
        config_path=CONFIG,
        environ={},
        state_dir_override=tmp_path,
    )
    assert report["mode"] == "fixture"
    assert report["capture_complete"] is True
    assert report["network_used"] is False
    assert report["upstream_point_in_time_snapshot_claim"] is False
    assert report["objects"] == 3
    assert report["relations"] == 1
    assert report["chunks"] >= 3
    assert report["quarantine_counts"] == {}
    assert report["required_projections"] == ["exact", "lexical", "graph"]
    assert report["live_maintained_serving"] is False

    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        active = store.connection.execute(
            "SELECT generation_id,manifest_sha256 FROM active_generations "
            "WHERE domain='cti' AND scope_id='opencti-sanitized' "
            "AND corpus_id='opencti-readonly'"
        ).fetchone()
        assert active is not None
        assert active["generation_id"] == report["generation_id"]
        jobs = {
            row["backend"]: row["status"]
            for row in store.connection.execute(
                "SELECT backend,status FROM projection_jobs "
                "WHERE generation_id=?",
                (report["generation_id"],),
            )
        }
        assert jobs == {"exact": "verified", "graph": "verified", "lexical": "verified"}
