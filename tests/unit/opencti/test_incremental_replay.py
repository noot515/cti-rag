from __future__ import annotations

from pathlib import Path

import pytest

from packages.evidence.store import EvidenceStore
from packages.integrations.opencti.checkpoint import (
    CheckpointKey,
    CheckpointNamespaceMismatch,
    OpenCTICheckpointLedger,
)
from packages.integrations.opencti.reader import (
    CapturePage,
    CapturedRecord,
    OpenCTIAmbiguousOrdering,
    OpenCTIReader,
    RawPayloadRef,
    _raw_ref,
)


def _record(source_id: str, *, modified: str, updated: str, name: str = "x"):
    payload = {
        "id": source_id,
        "standard_id": source_id,
        "entity_type": "Vulnerability",
        "modified": modified,
        "updated_at": updated,
        "name": name,
    }
    return CapturedRecord(
        kind="vulnerability",
        source_instance="source",
        source_object_id=source_id,
        payload=payload,
        raw_payload=_raw_ref(payload),
        captured_at="2026-09-18T00:00:00Z",
        page_index=0,
        cursor_before=None,
        cursor_after="c1",
    )


def _page(record, *, filters=None):
    return CapturePage(
        kind="vulnerability",
        source_instance="source",
        filters=dict(filters or {}),
        page_index=0,
        cursor_before=None,
        cursor_after="c1",
        has_next_page=False,
        global_count=1,
        capture_started_at="2026-09-18T00:00:00Z",
        capture_completed_at="2026-09-18T00:00:01Z",
        records=(record,),
    )


def test_ingestion_and_published_cursors_are_distinct_until_activation(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        ledger = OpenCTICheckpointLedger(store)
        key = CheckpointKey.create(
            source_instance="source",
            domain="cti",
            scope_id="scope",
            supported_type="vulnerability",
            filters={},
        )
        ledger.begin_run(
            key,
            run_id="run-1",
            source_version="7.260914.0",
            scan_bounds={"mode": "full"},
        )
        ledger.record_page(
            key,
            run_id="run-1",
            page=_page(_record(
                "vulnerability--11111111-1111-4111-8111-111111111111",
                modified="2026-09-01T00:00:00Z",
                updated="2026-09-02T00:00:00Z",
            )),
        )
        state = ledger.get(key)
        assert state is not None
        assert state.ingestion_cursor == {
            "after": "c1",
            "has_next_page": False,
            "page_index": 0,
        }
        assert state.published_cursor is None
        assert ledger.page_count(key, run_id="run-1") == 1


def test_replayed_page_is_idempotent_and_filter_namespace_isolated(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        ledger = OpenCTICheckpointLedger(store)
        base = CheckpointKey.create(
            source_instance="source",
            domain="cti",
            scope_id="scope",
            supported_type="vulnerability",
            filters={},
        )
        other = CheckpointKey.create(
            source_instance="source",
            domain="cti",
            scope_id="scope",
            supported_type="vulnerability",
            filters={"updated_since": "2026-09-01"},
        )
        ledger.begin_run(
            base, run_id="run", source_version="7.260914.0",
            scan_bounds={"mode": "full"},
        )
        page = _page(_record(
            "vulnerability--11111111-1111-4111-8111-111111111111",
            modified="2026-09-01T00:00:00Z",
            updated="2026-09-02T00:00:00Z",
        ))
        ledger.record_page(base, run_id="run", page=page)
        ledger.record_page(base, run_id="run", page=page)
        assert ledger.page_count(base, run_id="run") == 1
        assert ledger.get(other) is None
        with pytest.raises(CheckpointNamespaceMismatch):
            ledger.record_page(other, run_id="run", page=page)


class _DuplicateTransport:
    platform_version = "7.260914.0"

    def __init__(self, rows):
        self.rows = rows

    def list_page(self, kind, *, filters, first, after):
        return {
            "entities": list(self.rows),
            "pagination": {
                "endCursor": "done",
                "hasNextPage": False,
                "globalCount": 1,
            },
        }


def test_out_of_order_older_duplicate_cannot_replace_newer_source_revision():
    source_id = "vulnerability--11111111-1111-4111-8111-111111111111"
    newer = _record(
        source_id,
        modified="2026-09-02T00:00:00Z",
        updated="2026-09-03T00:00:00Z",
        name="newer",
    ).payload
    older = _record(
        source_id,
        modified="2026-09-01T00:00:00Z",
        updated="2026-09-04T00:00:00Z",
        name="older",
    ).payload
    capture = OpenCTIReader(
        _DuplicateTransport([newer, older]),
        source_instance="source",
    ).scan_complete(kinds=("vulnerability",))
    assert len(capture.records) == 1
    assert capture.records[0].payload["name"] == "newer"
    assert any("older duplicate ignored" in item for item in capture.consistency_warnings)


def test_equal_source_version_with_different_payload_is_ambiguous():
    source_id = "vulnerability--11111111-1111-4111-8111-111111111111"
    first = _record(
        source_id,
        modified="2026-09-01T00:00:00Z",
        updated="2026-09-02T00:00:00Z",
        name="a",
    ).payload
    second = dict(first, name="b")
    with pytest.raises(OpenCTIAmbiguousOrdering):
        OpenCTIReader(
            _DuplicateTransport([first, second]),
            source_instance="source",
        ).scan_complete(kinds=("vulnerability",))
