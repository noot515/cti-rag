"""Bounded, cursor-safe read capture for OpenCTI."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import random
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

from packages.evidence.ids import canonical_json

from .client import OpenCTIReadError, OpenCTITransientReadError


CAPTURE_KINDS = ("attack_pattern", "vulnerability", "report", "relationship")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class OpenCTIPageTransport(Protocol):
    platform_version: str

    def list_page(
        self,
        kind: str,
        *,
        filters: Mapping[str, Any] | None,
        first: int,
        after: str | None,
    ) -> dict[str, Any]: ...


class OpenCTICursorError(OpenCTIReadError):
    pass


class OpenCTIPartialScan(OpenCTIReadError):
    pass


@dataclass(frozen=True)
class RawPayloadRef:
    sha256: str
    byte_length: int


@dataclass(frozen=True)
class CapturedRecord:
    kind: str
    source_instance: str
    source_object_id: str
    payload: dict[str, Any]
    raw_payload: RawPayloadRef
    captured_at: str
    page_index: int
    cursor_before: str | None
    cursor_after: str | None


@dataclass(frozen=True)
class CapturePage:
    kind: str
    source_instance: str
    filters: dict[str, Any]
    page_index: int
    cursor_before: str | None
    cursor_after: str | None
    has_next_page: bool
    global_count: int | None
    capture_started_at: str
    capture_completed_at: str
    records: tuple[CapturedRecord, ...]


@dataclass(frozen=True)
class CompleteCapture:
    schema_version: str
    source_instance: str
    platform_version: str
    capture_started_at: str
    capture_completed_at: str
    order_field: str
    stix_modified_semantics: str
    complete: bool
    pages: tuple[CapturePage, ...]
    records: tuple[CapturedRecord, ...]
    duplicate_records: int
    consistency_warnings: tuple[str, ...]


def _source_object_id(payload: Mapping[str, Any]) -> str:
    value = payload.get("standard_id") or payload.get("id")
    if not isinstance(value, str) or not value.strip():
        raise OpenCTIReadError("captured OpenCTI entity has no standard_id or id")
    return value.strip()


def _raw_ref(payload: Mapping[str, Any]) -> RawPayloadRef:
    encoded = canonical_json(dict(payload)).encode("utf-8")
    return RawPayloadRef(sha256=sha256(encoded).hexdigest(), byte_length=len(encoded))


class RecordedOpenCTITransport:
    """Sanitized deterministic page source used by default tests and CLI."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        if payload.get("schema_version") != "opencti-recorded-capture-v1":
            raise OpenCTIReadError("unsupported recorded OpenCTI fixture schema")
        self.platform_version = str(payload.get("platform_version") or "")
        pages = payload.get("pages")
        if not isinstance(pages, dict):
            raise OpenCTIReadError("recorded OpenCTI fixture lacks pages")
        self._pages = pages

    @classmethod
    def from_path(cls, path: Path | str) -> "RecordedOpenCTITransport":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OpenCTIReadError("recorded OpenCTI fixture is unreadable") from exc
        return cls(payload)

    def list_page(
        self,
        kind: str,
        *,
        filters: Mapping[str, Any] | None,
        first: int,
        after: str | None,
    ) -> dict[str, Any]:
        if first < 1 or first > 200:
            raise ValueError("OpenCTI page size must be in [1, 200]")
        entries = self._pages.get(kind, [])
        if not isinstance(entries, list):
            raise OpenCTIReadError(f"recorded pages for {kind} are invalid")
        for entry in entries:
            if entry.get("after") == after:
                entities = entry.get("entities")
                pagination = entry.get("pagination")
                if not isinstance(entities, list) or not isinstance(pagination, dict):
                    raise OpenCTIReadError("recorded page lacks entities/pagination")
                return {"entities": entities[:first], "pagination": dict(pagination)}
        raise OpenCTIReadError(
            f"recorded fixture has no {kind} page for cursor {after!r}"
        )


class OpenCTIReader:
    def __init__(
        self,
        transport: OpenCTIPageTransport,
        *,
        source_instance: str,
        page_size: int = 100,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        max_pages_per_kind: int = 10000,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float], float] | None = None,
    ) -> None:
        if page_size < 1 or page_size > 200:
            raise ValueError("page_size must be in [1, 200]")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0 or max_retries > 5:
            raise ValueError("max_retries must be in [0, 5]")
        self.transport = transport
        self.source_instance = source_instance
        self.page_size = page_size
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_pages_per_kind = max_pages_per_kind
        self.sleep = sleep
        self.jitter = jitter or (lambda cap: random.uniform(0.0, cap))

    def _call_page(
        self,
        kind: str,
        *,
        filters: Mapping[str, Any] | None,
        after: str | None,
        deadline: float,
    ) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            if time.monotonic() >= deadline:
                raise OpenCTIPartialScan("OpenCTI capture deadline expired")
            try:
                return self.transport.list_page(
                    kind,
                    filters=filters,
                    first=self.page_size,
                    after=after,
                )
            except OpenCTITransientReadError:
                if attempt >= self.max_retries:
                    raise
                cap = min(2.0, 0.25 * (2 ** attempt))
                self.sleep(max(0.0, min(cap, self.jitter(cap))))
        raise AssertionError("retry loop exhausted")

    def scan_kind(
        self,
        kind: str,
        *,
        filters: Mapping[str, Any] | None = None,
    ) -> tuple[CapturePage, ...]:
        if kind not in CAPTURE_KINDS:
            raise ValueError(f"unsupported capture kind: {kind}")
        deadline = time.monotonic() + self.timeout_seconds
        after: str | None = None
        seen_cursors: set[str] = set()
        pages: list[CapturePage] = []
        for page_index in range(self.max_pages_per_kind):
            started = _now()
            result = self._call_page(kind, filters=filters, after=after, deadline=deadline)
            completed = _now()
            entities = result.get("entities")
            pagination = result.get("pagination")
            if not isinstance(entities, list) or not isinstance(pagination, dict):
                raise OpenCTIReadError("OpenCTI page result lacks entities/pagination")
            end_cursor_raw = pagination.get("endCursor")
            end_cursor = str(end_cursor_raw) if end_cursor_raw is not None else None
            has_next = bool(pagination.get("hasNextPage"))
            if has_next:
                if not end_cursor or end_cursor == after or end_cursor in seen_cursors:
                    raise OpenCTICursorError(
                        f"{kind} pagination cursor repeated or did not advance"
                    )
                seen_cursors.add(end_cursor)
            captured: list[CapturedRecord] = []
            for entity in entities:
                if not isinstance(entity, dict):
                    raise OpenCTIReadError("OpenCTI entity is not an object")
                captured.append(
                    CapturedRecord(
                        kind=kind,
                        source_instance=self.source_instance,
                        source_object_id=_source_object_id(entity),
                        payload=dict(entity),
                        raw_payload=_raw_ref(entity),
                        captured_at=_iso(completed),
                        page_index=page_index,
                        cursor_before=after,
                        cursor_after=end_cursor,
                    )
                )
            global_count = pagination.get("globalCount")
            pages.append(
                CapturePage(
                    kind=kind,
                    source_instance=self.source_instance,
                    filters=dict(filters or {}),
                    page_index=page_index,
                    cursor_before=after,
                    cursor_after=end_cursor,
                    has_next_page=has_next,
                    global_count=int(global_count) if global_count is not None else None,
                    capture_started_at=_iso(started),
                    capture_completed_at=_iso(completed),
                    records=tuple(captured),
                )
            )
            if not has_next:
                return tuple(pages)
            after = end_cursor
        raise OpenCTIPartialScan(
            f"{kind} exceeded max_pages_per_kind={self.max_pages_per_kind}"
        )

    def scan_complete(
        self,
        *,
        filters_by_kind: Mapping[str, Mapping[str, Any]] | None = None,
        kinds: Sequence[str] = CAPTURE_KINDS,
    ) -> CompleteCapture:
        started = _now()
        pages: list[CapturePage] = []
        for kind in kinds:
            pages.extend(
                self.scan_kind(kind, filters=(filters_by_kind or {}).get(kind))
            )

        latest: dict[tuple[str, str], CapturedRecord] = {}
        duplicates = 0
        warnings: list[str] = []
        for page in pages:
            for record in page.records:
                key = (record.kind, record.source_object_id)
                previous = latest.get(key)
                if previous is not None:
                    duplicates += 1
                    if previous.raw_payload.sha256 != record.raw_payload.sha256:
                        warnings.append(
                            f"entity changed during scan: {record.kind}:{record.source_object_id}"
                        )
                latest[key] = record
        completed = _now()
        return CompleteCapture(
            schema_version="opencti-complete-capture-v1",
            source_instance=self.source_instance,
            platform_version=str(self.transport.platform_version),
            capture_started_at=_iso(started),
            capture_completed_at=_iso(completed),
            order_field="updated_at",
            stix_modified_semantics=(
                "updated_at is OpenCTI platform ordering metadata; STIX modified is "
                "preserved independently as semantic provenance"
            ),
            complete=True,
            pages=tuple(pages),
            records=tuple(latest[key] for key in sorted(latest)),
            duplicate_records=duplicates,
            consistency_warnings=tuple(dict.fromkeys(warnings)),
        )


def raw_payload_bytes(record: CapturedRecord) -> bytes:
    encoded = canonical_json(record.payload).encode("utf-8")
    if sha256(encoded).hexdigest() != record.raw_payload.sha256:
        raise OpenCTIReadError("captured payload hash changed after capture")
    return encoded


__all__ = [
    "CAPTURE_KINDS", "CapturePage", "CapturedRecord", "CompleteCapture",
    "OpenCTICursorError", "OpenCTIPageTransport", "OpenCTIPartialScan",
    "OpenCTIReader", "RawPayloadRef", "RecordedOpenCTITransport",
    "raw_payload_bytes",
]
