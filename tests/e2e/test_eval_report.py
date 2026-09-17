from __future__ import annotations

import csv
import json
from pathlib import Path

from benchmark.advanced.report import MetricResult, MetricStatus
from benchmark.advanced.run_answer_eval import run_answer_evaluation
from benchmark.advanced.run_retrieval_eval import _report_files
from benchmark.advanced.splits import QueryGrouping, grouped_split
from packages.evidence.config import load_advanced_rag_config


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / "benchmark" / "advanced" / "configs" / "fixture.yaml"


def metric(value):
    return MetricResult(
        status=MetricStatus.OK,
        support_count=2,
        annotation_coverage=1.0,
        value=value,
    ).model_dump(mode="json")


def test_report_bundle_contains_required_artifacts_and_honest_gates(tmp_path):
    config = load_advanced_rag_config(CONFIG)
    predictions = [
        {
            "query_id": "q1",
            "query": "fixture one",
            "task": "mapping",
            "execution_status": "ok",
            "execution_errors": [],
            "latency_ms": 1.0,
            "channel_rankings": {},
            "rankings": {},
            "predicted_paths": [],
            "evaluation": {},
        },
        {
            "query_id": "q2",
            "query": "fixture two",
            "task": "general",
            "execution_status": "failed",
            "execution_errors": ["TimeoutError"],
            "latency_ms": 3.0,
            "channel_rankings": {},
            "rankings": {},
            "predicted_paths": [],
            "evaluation": {},
        },
    ]
    split = grouped_split(
        (
            QueryGrouping("q1", "c1", "f1"),
            QueryGrouping("q2", "c2", "f2"),
        )
    )
    unavailable = MetricResult(
        status=MetricStatus.NOT_RUN,
        reason="fixture unavailable",
        support_count=0,
        annotation_coverage=0.0,
        value=None,
    ).model_dump(mode="json")
    retrieval_metrics = {
        name: {"recall@10": metric(0.5)}
        for name in ("R1", "R2", "R3", "R4", "R5")
    }
    retrieval_metrics.update(
        {
            "R6": {"recall@10": dict(unavailable)},
            "C1-basic": {"context_quality": dict(unavailable)},
            "C1-structured": {"context_quality": dict(unavailable)},
            "L0": {"object_recall@10": dict(unavailable)},
            "gates": {"real_quality_promotion": dict(unavailable)},
        }
    )
    _report_files(
        output=tmp_path,
        config=config,
        predictions=predictions,
        ingest_report={
            "generation_id": "g1",
            "network_used": False,
            "frozen_split": split.as_dict(),
        },
        retrieval_metrics=retrieval_metrics,
    )

    required = {
        "config.snapshot.yaml",
        "environment.json",
        "corpus.manifest.snapshot.json",
        "split.manifest.json",
        "per_query.jsonl",
        "retrieval_metrics.json",
        "answer_metrics.json",
        "latency_metrics.json",
        "ablation_summary.csv",
        "report.md",
    }
    assert required <= {path.name for path in tmp_path.iterdir()}
    environment = json.loads((tmp_path / "environment.json").read_text())
    assert environment["network_used"] is False
    assert environment["throughput_claim"] is False
    split_payload = json.loads((tmp_path / "split.manifest.json").read_text())
    assert split_payload["seed"] == split.seed
    assert split_payload["grouping_sha256"] == split.grouping_sha256
    assert split_payload["split_sha256"] == split.split_sha256
    latency = json.loads((tmp_path / "latency_metrics.json").read_text())
    assert latency["sample_count"] == 2
    assert latency["concurrency"] == 1
    lines = (tmp_path / "per_query.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["execution_status"] == "failed"
    with (tmp_path / "ablation_summary.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["name"] for row in rows} == {
        "R1",
        "R2",
        "R3",
        "R4",
        "R5",
        "R6",
        "C1-basic",
        "C1-structured",
    }
    assert "not a real-quality promotion claim" in (tmp_path / "report.md").read_text()


def test_answer_runner_requires_permission_and_exact_model_for_egress(monkeypatch, tmp_path):
    from benchmark.advanced import run_answer_eval as module

    monkeypatch.setattr(
        module,
        "run_retrieval_evaluation",
        lambda **_kwargs: {"queries": 2},
    )
    (tmp_path / "report.md").write_text("# report\n", encoding="utf-8")

    try:
        run_answer_evaluation(
            config_path=CONFIG,
            output=tmp_path,
            allow_model_egress=True,
            generator_model=None,
        )
    except ValueError as exc:
        assert "exact --generator-model" in str(exc)
    else:
        raise AssertionError("model egress was accepted without an exact generator model")

    result = run_answer_evaluation(config_path=CONFIG, output=tmp_path)
    assert result["answer_quality"] == "not_run"
    metrics = json.loads((tmp_path / "answer_metrics.json").read_text())
    assert metrics["answer_quality"]["status"] == "not_run"
    assert metrics["citation_validity"]["value"] is None
    assert metrics["citation_support"]["value"] is None
