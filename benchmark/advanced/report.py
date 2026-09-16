"""Structured, honest reporting contracts for L0 baseline runs."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, str_strip_whitespace=True)


class MetricStatus(str, Enum):
    OK = "ok"
    NOT_RUN = "not_run"
    NOT_APPLICABLE = "not_applicable"
    NOT_COMPARABLE = "not_comparable"
    INCONCLUSIVE = "inconclusive"


class MetricResult(ReportModel):
    status: MetricStatus
    reason: str | None = None
    support_count: int = Field(ge=0)
    value: float | None = None

    @model_validator(mode="after")
    def honest_status_value(self) -> "MetricResult":
        unavailable = {
            MetricStatus.NOT_RUN,
            MetricStatus.NOT_APPLICABLE,
            MetricStatus.NOT_COMPARABLE,
            MetricStatus.INCONCLUSIVE,
        }
        if self.status in unavailable and self.value is not None:
            raise ValueError("unavailable/inconclusive metrics must serialize with value=null")
        if self.status == MetricStatus.OK:
            if self.value is None:
                raise ValueError("ok metrics require a value")
            if self.support_count < 1:
                raise ValueError("ok metrics require support_count >= 1")
        elif not self.reason:
            raise ValueError("non-ok metric status requires a reason")
        return self


class L0RunConfig(ReportModel):
    schema_version: Literal["l0-run-config-v1"] = "l0-run-config-v1"
    transport: Literal["http", "callable"] = "http"
    server_url: str = "http://localhost:8000"
    test_user_id: int = Field(gt=0)
    db_id: str = Field(min_length=1)
    corpus_manifest: str = Field(min_length=1)
    query_manifest: str = Field(min_length=1)
    canonical_object_mapping: str | None = None
    request_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    top_k: int = Field(default=10, ge=1, le=50)
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    use_graph: bool = False
    use_web: bool = False
    rewrite_mode: str = Field(default="legacy-configured", min_length=1)
    legacy_reranking: str = Field(default="legacy-pipeline-may-rerank-before-or-after-retrieval", min_length=1)
    requested_model_provider: str | None = None
    requested_model_name: str | None = None

    @model_validator(mode="after")
    def baseline_is_offline_from_web(self) -> "L0RunConfig":
        if self.use_web:
            raise ValueError("L0 advanced evaluation boundary requires web retrieval disabled")
        return self

    def redacted_snapshot(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class QueryRunRecord(ReportModel):
    query_id: str = Field(min_length=1)
    status: Literal["ok", "failed", "not_run"]
    answer: str | None = None
    reason: str | None = None
    elapsed_ms: float | None = Field(default=None, ge=0)
    actual_model_provider: str | None = None
    actual_model_name: str | None = None
    route_reason: str | None = None

    @model_validator(mode="after")
    def validate_run_status(self) -> "QueryRunRecord":
        if self.status == "ok" and self.answer is None:
            raise ValueError("successful query runs require an assembled answer")
        if self.status != "ok" and not self.reason:
            raise ValueError("failed/not_run query runs require a reason")
        return self


class BaselineRunReport(ReportModel):
    schema_version: Literal["baseline-run-report-v1"] = "baseline-run-report-v1"
    run_id: str = Field(min_length=1)
    created_at: datetime
    preflight_only: bool
    predecessor_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    config: dict[str, Any]
    corpus_manifest_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_runs: tuple[QueryRunRecord, ...]
    metrics: dict[str, MetricResult]
    total_queries: int = Field(ge=0)
    successful_queries: int = Field(ge=0)
    failed_queries: int = Field(ge=0)
    not_run_queries: int = Field(ge=0)
    failures_in_denominator: bool = True
    notes: tuple[str, ...] = ()

    @field_validator("created_at", mode="before")
    @classmethod
    def normalize_created_at(cls, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def counts_match(self) -> "BaselineRunReport":
        if self.total_queries != len(self.query_runs):
            raise ValueError("total_queries must equal query_runs length")
        counts = {
            "ok": sum(item.status == "ok" for item in self.query_runs),
            "failed": sum(item.status == "failed" for item in self.query_runs),
            "not_run": sum(item.status == "not_run" for item in self.query_runs),
        }
        if self.successful_queries != counts["ok"] or self.failed_queries != counts["failed"] or self.not_run_queries != counts["not_run"]:
            raise ValueError("query status counts do not match query_runs")
        return self


__all__ = ["BaselineRunReport", "L0RunConfig", "MetricResult", "MetricStatus", "QueryRunRecord"]
