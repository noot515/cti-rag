"""Reproducible L0 adapter that preserves the legacy chat baseline."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import time
from typing import Any, Iterable, Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen
import uuid

import yaml

from .dataset import (
    EvaluationDataError,
    file_sha256,
    load_corpus_manifest,
    load_query_records,
    manifest_fingerprint,
    validate_corpus_manifest,
)
from .report import BaselineRunReport, L0RunConfig, MetricResult, MetricStatus, QueryRunRecord

PREDECESSOR_SHA = "312e11837bde5b525d277bf7387c57ce30487bb3"


class LegacyTransportError(RuntimeError):
    pass


class StreamingTransport(Protocol):
    def post_stream(self, url: str, payload: dict[str, Any], timeout_seconds: float) -> Iterable[bytes | str]: ...


class UrllibStreamingTransport:
    def post_stream(self, url: str, payload: dict[str, Any], timeout_seconds: float) -> Iterable[bytes]:
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                for line in response:
                    yield line
        except (TimeoutError, socket.timeout) as exc:
            raise LegacyTransportError("legacy HTTP request timed out") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise LegacyTransportError("legacy HTTP request timed out") from exc
            raise LegacyTransportError("legacy HTTP request failed") from exc


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _repo_path(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise EvaluationDataError(f"evaluation path escapes repository root: {value}") from exc
    return candidate


def load_l0_config(path: Path) -> L0RunConfig:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return L0RunConfig.model_validate(payload)
    except Exception as exc:
        raise EvaluationDataError(f"invalid L0 config: {path}") from exc


def _build_payload(config: L0RunConfig, query: str) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "db_id": config.db_id,
        "show_retrieval_info": True,
        "use_web": False,
        "use_graph": config.use_graph,
        "top_k": config.top_k,
        "threshold": config.threshold,
    }
    if config.requested_model_provider:
        meta["model_provider"] = config.requested_model_provider
    if config.requested_model_name:
        meta["model_name"] = config.requested_model_name
    return {"query": query, "user_id": config.test_user_id, "meta": meta}


def _parse_stream(lines: Iterable[bytes | str]) -> tuple[str, dict[str, Any]]:
    answer_parts: list[str] = []
    observed_meta: dict[str, Any] = {}
    saw_finished = False
    for raw_line in lines:
        text = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if not text.strip():
            continue
        try:
            chunk = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LegacyTransportError("legacy stream returned invalid JSON") from exc
        status = chunk.get("status")
        if status == "error":
            raise LegacyTransportError("legacy stream returned an error status")
        response = chunk.get("response")
        if isinstance(response, str):
            answer_parts.append(response)
        meta = chunk.get("meta")
        if isinstance(meta, dict):
            for key in ("actual_model_provider", "actual_model_name", "route_reason", "degraded",
                        "expected_model_provider", "expected_model_name"):
                if key in meta:
                    observed_meta[key] = meta[key]
        if status == "finished":
            saw_finished = True
    if not saw_finished:
        raise LegacyTransportError("legacy stream ended without a finished status")
    return "".join(answer_parts), observed_meta


def _metric_bundle(config: L0RunConfig, *, preflight_only: bool, successful_queries: int) -> dict[str, MetricResult]:
    if config.canonical_object_mapping:
        object_metric = MetricResult(
            status=MetricStatus.NOT_RUN,
            reason="canonical mapping is configured, but Prompt 02 intentionally defers object-metric implementation",
            support_count=0,
            value=None,
        )
    else:
        object_metric = MetricResult(
            status=MetricStatus.NOT_COMPARABLE,
            reason="no verified canonical legacy-object mapping configured",
            support_count=0,
            value=None,
        )
    answer_metric = MetricResult(
        status=MetricStatus.NOT_RUN,
        reason=("preflight-only mode performs no answer generation or quality scoring" if preflight_only
                else "Prompt 02 preserves answer generation traces but does not implement a new quality metric"),
        support_count=successful_queries,
        value=None,
    )
    return {"l0_object_recall": object_metric, "l0_answer_quality": answer_metric}


def run_baseline(config: L0RunConfig, *, root: Path | None = None, preflight_only: bool = False,
                 transport: StreamingTransport | None = None) -> BaselineRunReport:
    root = (root or _repo_root()).resolve()
    manifest_path = _repo_path(root, config.corpus_manifest)
    query_path = _repo_path(root, config.query_manifest)
    manifest = load_corpus_manifest(manifest_path)
    validate_corpus_manifest(manifest, root)
    queries = load_query_records(query_path)

    runs: list[QueryRunRecord] = []
    if preflight_only:
        runs = [QueryRunRecord(query_id=item.query_id, status="not_run", reason="preflight-only") for item in queries]
    else:
        if config.transport != "http":
            raise EvaluationDataError("only http transport is executable in the repository L0 adapter")
        transport = transport or UrllibStreamingTransport()
        endpoint = config.server_url.rstrip("/") + "/chat/stream"
        for item in queries:
            started = time.perf_counter()
            try:
                answer, meta = _parse_stream(
                    transport.post_stream(endpoint, _build_payload(config, item.query), config.request_timeout_seconds)
                )
                runs.append(QueryRunRecord(
                    query_id=item.query_id,
                    status="ok",
                    answer=answer,
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    actual_model_provider=meta.get("actual_model_provider"),
                    actual_model_name=meta.get("actual_model_name"),
                    route_reason=meta.get("route_reason"),
                ))
            except Exception as exc:
                reason = exc.__class__.__name__
                if isinstance(exc, LegacyTransportError) and "timed out" in str(exc).lower():
                    reason = "LegacyTransportTimeout"
                runs.append(QueryRunRecord(
                    query_id=item.query_id,
                    status="failed",
                    reason=reason,
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                ))

    successful = sum(item.status == "ok" for item in runs)
    failed = sum(item.status == "failed" for item in runs)
    not_run = sum(item.status == "not_run" for item in runs)
    notes = (
        "web retrieval is forced off by the L0 evaluation boundary",
        f"rewrite setting is recorded as {config.rewrite_mode!r} but is not presented as a controlled ablation",
        f"legacy reranking behavior is recorded as {config.legacy_reranking!r}",
    )
    return BaselineRunReport(
        run_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        preflight_only=preflight_only,
        predecessor_sha=PREDECESSOR_SHA,
        config=config.redacted_snapshot(),
        corpus_manifest_fingerprint=manifest_fingerprint(manifest),
        query_manifest_sha256=file_sha256(query_path),
        query_runs=tuple(runs),
        metrics=_metric_bundle(config, preflight_only=preflight_only, successful_queries=successful),
        total_queries=len(runs),
        successful_queries=successful,
        failed_queries=failed,
        not_run_queries=not_run,
        failures_in_denominator=True,
        notes=notes,
    )


def write_report(report: BaselineRunReport, output: Path) -> Path:
    if output.suffix.lower() == ".json":
        output.parent.mkdir(parents=True, exist_ok=True)
        target = output
    else:
        output.mkdir(parents=True, exist_ok=True)
        target = output / "report.json"
    target.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run or preflight the preserved L0 legacy baseline")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    config = load_l0_config(Path(args.config))
    report = run_baseline(config, preflight_only=args.preflight_only)
    target = write_report(report, Path(args.output))
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
