from __future__ import annotations

import json
from pathlib import Path

from packages.integrations.opencti.normalizer import normalize_complete_capture
from packages.integrations.opencti.reader import OpenCTIReader, RecordedOpenCTITransport


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests" / "fixtures" / "opencti" / "recorded_capture.json"


def capture_from_payload(payload, tmp_path: Path):
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    transport = RecordedOpenCTITransport.from_path(path)
    return OpenCTIReader(
        transport,
        source_instance="test-opencti",
        sleep=lambda _x: None,
        jitter=lambda _cap: 0.0,
    ).scan_complete()


def test_sanitized_capture_normalizes_with_provenance_and_explicit_relationship():
    transport = RecordedOpenCTITransport.from_path(FIXTURE)
    capture = OpenCTIReader(
        transport,
        source_instance="opencti-sanitized-fixture",
        sleep=lambda _x: None,
        jitter=lambda _cap: 0.0,
    ).scan_complete()
    normalized = normalize_complete_capture(
        capture,
        scope_id="opencti-sanitized",
        source_uri="recorded://fixture",
        sanitized_public_fixture=True,
    )
    batch = normalized.batch
    assert len(batch.objects) == 3
    assert len(batch.relations) == 1
    assert batch.quarantine_counts == {}
    assert all(obj.source_refs[0].upstream_origin.startswith("opencti:") for obj in batch.objects)
    assert all(obj.source_refs[0].raw_payload_sha256 in normalized.raw_payloads for obj in batch.objects)
    vulnerability = next(obj for obj in batch.objects if obj.object_type == "vulnerability")
    ids = {(item.namespace, item.value) for item in vulnerability.external_ids}
    assert ("cve", "CVE-2026-12345") in ids
    assert ("cwe", "CWE-79") in ids
    technique = next(obj for obj in batch.objects if obj.object_type == "technique")
    assert any(item.value == "T1059.001" for item in technique.external_ids)
    assert "tlp:clear" in technique.policy.dissemination
    assert batch.relations[0].normalized_relation == "uses"


def test_updated_at_change_does_not_manufacture_stix_revision(tmp_path: Path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    first_capture = capture_from_payload(payload, tmp_path)
    first = normalize_complete_capture(
        first_capture,
        scope_id="scope",
        source_uri="recorded://fixture",
        sanitized_public_fixture=True,
    )
    payload["pages"]["vulnerability"][0]["entities"][0]["updated_at"] = "2026-09-17T00:00:00Z"
    second_capture = capture_from_payload(payload, tmp_path)
    second = normalize_complete_capture(
        second_capture,
        scope_id="scope",
        source_uri="recorded://fixture",
        sanitized_public_fixture=True,
    )
    a = next(obj for obj in first.batch.objects if obj.object_type == "vulnerability")
    b = next(obj for obj in second.batch.objects if obj.object_type == "vulnerability")
    assert a.uid == b.uid
    assert a.revision_uid == b.revision_uid
    assert a.source_refs[0].raw_payload_sha256 != b.source_refs[0].raw_payload_sha256


def test_unmarked_live_record_is_not_promoted_to_public(tmp_path: Path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for kind in ("attack_pattern", "vulnerability", "report", "relationship"):
        for entity in payload["pages"][kind][0]["entities"]:
            entity.pop("objectMarking", None)
    capture = capture_from_payload(payload, tmp_path)
    normalized = normalize_complete_capture(
        capture,
        scope_id="restricted",
        source_uri="https://opencti.example",
        sanitized_public_fixture=False,
    )
    assert any(obj.policy.unresolved_markings for obj in normalized.batch.objects)
    assert all("tlp:clear" not in obj.policy.dissemination for obj in normalized.batch.objects)


def test_unsupported_relationship_is_quarantined(tmp_path: Path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["pages"]["relationship"][0]["entities"][0]["relationship_type"] = "related-to"
    capture = capture_from_payload(payload, tmp_path)
    normalized = normalize_complete_capture(
        capture,
        scope_id="scope",
        source_uri="recorded://fixture",
        sanitized_public_fixture=True,
    )
    assert len(normalized.batch.relations) == 0
    assert normalized.quarantine_counts
    assert any(record.record_kind == "relation" for record in normalized.batch.quarantined)


def test_malformed_stix_identifier_is_quarantined(tmp_path: Path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["pages"]["attack_pattern"][0]["entities"][0]["standard_id"] = "attack-pattern--not-a-uuid"
    # Remove relationship to isolate object normalization failure.
    payload["pages"]["relationship"][0]["entities"] = []
    payload["pages"]["relationship"][0]["pagination"]["globalCount"] = 0
    capture = capture_from_payload(payload, tmp_path)
    normalized = normalize_complete_capture(
        capture,
        scope_id="scope",
        source_uri="recorded://fixture",
        sanitized_public_fixture=True,
    )
    assert any(record.record_kind == "object" for record in normalized.batch.quarantined)
