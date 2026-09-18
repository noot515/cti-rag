from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from packages.integrations.opencti.client import (
    OpenCTIAccessError,
    OpenCTITransientReadError,
)
from packages.integrations.opencti.reader import (
    OpenCTICursorError,
    OpenCTIReader,
    RecordedOpenCTITransport,
)


ROOT = Path(__file__).resolve().parents[3]


class ScriptTransport:
    platform_version = "7.260914.0"

    def __init__(self, script):
        self.script = dict(script)
        self.calls = []

    def list_page(self, kind, *, filters, first, after):
        self.calls.append((kind, filters, first, after))
        value = self.script[(kind, after)]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = value()
        return value


def page(entities, *, end=None, next_page=False, count=None):
    return {
        "entities": entities,
        "pagination": {
            "startCursor": None,
            "endCursor": end,
            "hasNextPage": next_page,
            "hasPreviousPage": False,
            "globalCount": len(entities) if count is None else count,
        },
    }


def entity(stix_id, internal):
    return {
        "id": internal,
        "standard_id": stix_id,
        "entity_type": "Vulnerability",
        "updated_at": "2026-09-01T00:00:00Z",
        "modified": "2026-08-31T00:00:00Z",
        "name": "CVE-2026-12345",
    }


def test_bounded_pagination_overlap_and_capture_metadata():
    a = entity("vulnerability--11111111-1111-4111-8111-111111111111", "a")
    b = entity("vulnerability--22222222-2222-4222-8222-222222222222", "b")
    c = entity("vulnerability--33333333-3333-4333-8333-333333333333", "c")
    transport = ScriptTransport({
        ("vulnerability", None): page([a, b], end="c1", next_page=True, count=3),
        ("vulnerability", "c1"): page([b, c], end="c2", next_page=False, count=3),
    })
    reader = OpenCTIReader(
        transport,
        source_instance="test-source",
        page_size=2,
        sleep=lambda _x: None,
        jitter=lambda _cap: 0.0,
    )
    capture = reader.scan_complete(kinds=("vulnerability",))
    assert capture.complete is True
    assert capture.order_field == "updated_at"
    assert "STIX modified" in capture.stix_modified_semantics
    assert capture.duplicate_records == 1
    assert len(capture.records) == 3
    assert transport.calls == [
        ("vulnerability", None, 2, None),
        ("vulnerability", None, 2, "c1"),
    ]
    assert capture.pages[0].global_count == 3
    assert capture.pages[0].records[0].raw_payload.byte_length > 0


def test_nonadvancing_cursor_fails_closed():
    transport = ScriptTransport({
        ("vulnerability", None): page([entity("vulnerability--11111111-1111-4111-8111-111111111111", "a")], end="same", next_page=True),
        ("vulnerability", "same"): page([], end="same", next_page=True),
    })
    reader = OpenCTIReader(transport, source_instance="test", sleep=lambda _x: None)
    with pytest.raises(OpenCTICursorError, match="did not advance"):
        reader.scan_kind("vulnerability")


def test_transient_read_retries_but_access_failure_does_not():
    attempts = {"count": 0}

    def transient_once():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise OpenCTITransientReadError("timeout")
        return page([], end="done", next_page=False)

    transient = ScriptTransport({("report", None): transient_once})
    reader = OpenCTIReader(
        transient,
        source_instance="test",
        max_retries=2,
        sleep=lambda _x: None,
        jitter=lambda _cap: 0.0,
    )
    assert len(reader.scan_kind("report")) == 1
    assert attempts["count"] == 2

    denied = ScriptTransport({("report", None): OpenCTIAccessError("forbidden")})
    reader = OpenCTIReader(
        denied,
        source_instance="test",
        max_retries=5,
        sleep=lambda _x: None,
    )
    with pytest.raises(OpenCTIAccessError):
        reader.scan_kind("report")
    assert len(denied.calls) == 1


def test_recorded_transport_rejects_unknown_cursor(tmp_path: Path):
    payload = {
        "schema_version": "opencti-recorded-capture-v1",
        "platform_version": "7.260914.0",
        "pages": {"report": []},
    }
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    transport = RecordedOpenCTITransport.from_path(path)
    with pytest.raises(Exception, match="no report page"):
        transport.list_page("report", filters=None, first=10, after=None)


def test_fresh_import_does_not_import_pycti_or_legacy_services(tmp_path: Path):
    code = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
import packages.integrations.opencti.reader
assert 'pycti' not in sys.modules
assert 'rag.mq.task_worker' not in sys.modules
assert 'packages.manager.db_manager' not in sys.modules
print('ok')
"""
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
