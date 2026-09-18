from __future__ import annotations

from pathlib import Path

import pytest

from packages.indexing.orchestrator import InjectedPublicationCrash
from packages.integrations.opencti.sync import sync_once


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "benchmark" / "advanced" / "configs" / "opencti.yaml"


def test_unchanged_full_replay_has_zero_logical_changes(tmp_path: Path):
    first = sync_once(
        config_path=CONFIG,
        environ={},
        state_dir_override=tmp_path,
    )
    second = sync_once(
        config_path=CONFIG,
        environ={},
        state_dir_override=tmp_path,
    )
    assert first["generation_id"] == second["generation_id"]
    assert second["logical_changes"] == 0
    assert set(second["checkpoint_states"].values()) == {"published"}
    assert second["delivery_semantics"] == "at-least-once"
    assert second["incremental_projection_reuse"] is False


def test_activation_before_published_checkpoint_is_reconciled_on_restart(tmp_path: Path):
    with pytest.raises(InjectedPublicationCrash):
        sync_once(
            config_path=CONFIG,
            environ={},
            state_dir_override=tmp_path,
            crash_at="after_activation",
        )
    recovered = sync_once(
        config_path=CONFIG,
        environ={},
        state_dir_override=tmp_path,
    )
    assert recovered["recovered_publication_checkpoints"] >= 1
    assert set(recovered["checkpoint_states"].values()) == {"published"}


def test_failure_before_activation_never_advances_published_checkpoint(tmp_path: Path):
    with pytest.raises(InjectedPublicationCrash):
        sync_once(
            config_path=CONFIG,
            environ={},
            state_dir_override=tmp_path,
            crash_at="after_receipt:exact",
        )
    from packages.evidence.store import EvidenceStore
    from packages.integrations.opencti.checkpoint import (
        CheckpointKey,
        OpenCTICheckpointLedger,
    )
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        ledger = OpenCTICheckpointLedger(store)
        key = CheckpointKey.create(
            source_instance="opencti-sanitized-fixture",
            domain="cti",
            scope_id="opencti-sanitized",
            supported_type="vulnerability",
            filters={},
        )
        state = ledger.get(key)
        assert state is not None
        assert state.published_cursor is None
