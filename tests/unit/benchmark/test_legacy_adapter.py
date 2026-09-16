from __future__ import annotations

from pathlib import Path

from benchmark.advanced.legacy_adapter import LegacyTransportError, load_l0_config, run_baseline, write_report

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "benchmark" / "advanced" / "configs" / "legacy.yaml"


class RecordingTransport:
    def __init__(self):
        self.calls = []

    def post_stream(self, url, payload, timeout_seconds):
        self.calls.append((url, payload, timeout_seconds))
        return [
            b'{"response":"hello ","status":"loading","meta":{"actual_model_provider":"ollama","actual_model_name":"qwen3:30b","route_reason":"default_route"}}\n',
            b'{"response":"world","status":"loading","meta":{}}\n',
            b'{"response":null,"status":"finished","meta":{"actual_model_provider":"ollama","actual_model_name":"qwen3:30b","route_reason":"default_route"}}\n',
        ]


class TimeoutTransport:
    def post_stream(self, url, payload, timeout_seconds):
        raise LegacyTransportError("legacy HTTP request timed out")


def test_recorded_request_supplies_user_id_forces_web_off_and_assembles_stream():
    config = load_l0_config(CONFIG)
    transport = RecordingTransport()
    report = run_baseline(config, root=ROOT, transport=transport)

    assert report.successful_queries == 1
    assert report.failed_queries == 0
    assert report.query_runs[0].answer == "hello world"
    assert report.query_runs[0].actual_model_provider == "ollama"
    assert report.metrics["l0_object_recall"].status.value == "not_comparable"

    _, payload, _ = transport.calls[0]
    assert payload["user_id"] == 1
    assert payload["meta"]["use_web"] is False
    assert "history" not in payload


def test_timeout_remains_failed_query_in_denominator():
    config = load_l0_config(CONFIG)
    report = run_baseline(config, root=ROOT, transport=TimeoutTransport())
    assert report.total_queries == 1
    assert report.failed_queries == 1
    assert report.query_runs[0].status == "failed"
    assert report.query_runs[0].answer is None
    assert report.query_runs[0].reason == "LegacyTransportTimeout"
    assert report.failures_in_denominator is True


def test_preflight_is_network_free_and_writes_honest_report(tmp_path: Path):
    config = load_l0_config(CONFIG)
    report = run_baseline(config, root=ROOT, preflight_only=True)
    assert report.not_run_queries == 1
    assert report.metrics["l0_answer_quality"].status.value == "not_run"
    target = write_report(report, tmp_path / "l0-preflight")
    assert target.name == "report.json"
    assert target.is_file()
