"""Pinned CTIConnect external-corpus adapter.

The application never imports CTIConnect at runtime. This module reads a separately
checked-out public benchmark tree, verifies the pinned release, exposes query-only
records separately from labels, rebuilds lexical retrieval from text, and writes an
honest offline evaluation report.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping, Sequence

import yaml

from benchmark.advanced.dataset import QueryRecord
from benchmark.advanced.metrics import recall_at_k
from benchmark.advanced.report import MetricResult, MetricStatus
from benchmark.advanced.splits import QueryGrouping, grouped_split


PINNED_REPOSITORY = "peng-gao-lab/CTIConnect"
PINNED_COMMIT = "554797d69a51147f1f98fad7198cb2d2b183d0e9"
PINNED_VERSION = "v1.0.0"
EXPECTED_TOTAL = 1859
EXPECTED_TASKS: dict[str, dict[str, Any]] = {
    "rcm": {"category": "entity_linking", "count": 290, "eval_type": "single_id_match", "target_type": "cwe", "sha256": "8adc1dde139532b1be76774ca296b6a801159dba477d0df88a736e6b1c11097b"},
    "wim": {"category": "entity_linking", "count": 308, "eval_type": "single_id_match", "target_type": "cve", "sha256": "2f412b493e8aa6b5aa9a02d52eeafc02246d82e4c276eb78f71c1a5ea428c3f6"},
    "atd": {"category": "entity_linking", "count": 261, "eval_type": "single_id_match", "target_type": "mitre", "sha256": "34619e01add2a5e286df554f706b40a1f8bfa1e83d1a7c70c2365c128f6ca22f"},
    "esd": {"category": "entity_linking", "count": 280, "eval_type": "single_id_match", "target_type": "capec", "sha256": "56c0c3eb110ae1f57d58fc68fdec230b3077a0f6f9ce99b7f68c3b29f504f1d6"},
    "ata": {"category": "entity_attribution", "count": 160, "eval_type": "id_set_match", "target_type": "mitre", "sha256": "73e263e82144d097bd16896dbfe6324e1e275d9831adfae5fa53189ae51872bc"},
    "vca": {"category": "entity_attribution", "count": 219, "eval_type": "id_set_match", "target_type": "cwe", "sha256": "4cceb8527c055b6241882ab63490bc197becb4e3bdab08846350a2cebd0173f5"},
    "csc": {"category": "multi_doc_synthesis", "count": 111, "eval_type": "judge", "target_type": "free_text", "sha256": "4b6b58cd78355da308a7531c0a72f1003143f4c04e9fff5831f696ce234283e7"},
    "tap": {"category": "multi_doc_synthesis", "count": 135, "eval_type": "judge", "target_type": "free_text", "sha256": "ed97452acb273063569baa6f6f10c535d99a4591543b8ad1a7d4bd7fb851b09c"},
    "mla": {"category": "multi_doc_synthesis", "count": 95, "eval_type": "judge", "target_type": "free_text", "sha256": "74c58883ff578b0d26b3ec1f2511392d39e2a1c315b480a21fe84d3700d780eb"},
}
EXPECTED_KB_FILES = {
    "capec.jsonl": {"lines": 615, "sha256": "55e0ef116393ba2c3006e1518f49e1eff3c814d8a61c6ca2621e686f891424ba"},
    "cve.jsonl": {"lines": 3011, "sha256": "bbff0d6f1dc6d44a1fd37f60a76e5d0358bce2613a3e296b5c6a03290e7e8f29"},
    "cwe.jsonl": {"lines": 1342, "sha256": "3b9f9770c362162372a1f624bbce28fa1847b86351fd1af03c8a7b4008d5b00b"},
    "mitre.jsonl": {"lines": 1076, "sha256": "0a8baf003dbcbecd79b0e7ad1ba344cf16558f4169acb9b84b783d9bf2512b6c"},
}
EXPECTED_REPORT_COUNT = 321
TASK_TARGET_CORPUS = {
    "rcm": "cwe", "wim": "cve", "atd": "mitre", "esd": "capec",
    "ata": "mitre", "vca": "cwe", "csc": "report", "tap": "report", "mla": "report",
}
_TOKEN_RE = re.compile(r"CVE-\d{4}-\d{4,}|CWE-\d+|CAPEC-\d+|T\d{4}(?:\.\d{3})?|[A-Za-z0-9_]+", re.IGNORECASE)
_ID_PATTERNS = {
    "cve": re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE),
    "cwe": re.compile(r"CWE-\d+", re.IGNORECASE),
    "capec": re.compile(r"CAPEC-\d+", re.IGNORECASE),
    "mitre": re.compile(r"\bT\d{4}(?:\.\d{3})?\b", re.IGNORECASE),
}


class CTIConnectError(RuntimeError):
    pass


class CTIConnectUnavailable(CTIConnectError):
    pass


class CTIConnectAuditError(CTIConnectError):
    pass


@dataclass(frozen=True)
class CorpusDocument:
    document_id: str
    corpus_kind: str
    source_identifier: str
    title: str
    text: str
    provenance: dict[str, Any]


@dataclass(frozen=True)
class OfficialLabel:
    query_id: str
    task: str
    eval_type: str
    target_type: str
    target_id: str | None
    target_ids: tuple[str, ...]
    valid_target_ids: tuple[str, ...]
    reference_answer: str | None
    source_type: str
    source_id: str | None
    blog_ids: tuple[str, ...]
    construction_file: str | None


@dataclass(frozen=True)
class OfficialItemScore:
    precision: float
    recall: float
    f1: float
    exact_match: bool
    pred_ids: tuple[str, ...]
    canonical_gold_ids: tuple[str, ...]
    valid_ids: tuple[str, ...]


@dataclass(frozen=True)
class AuditReport:
    repository: str
    commit: str
    version: str
    total_queries: int
    task_counts: dict[str, int]
    task_sha256: dict[str, str]
    kb_sha256: dict[str, str]
    report_count: int
    report_sha256: str
    code_license: str
    data_license: str
    graph_assets: dict[str, Any]


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _nonempty_line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def resolve_external_root(path: Path | str | None = None, *, environ: Mapping[str, str] | None = None) -> Path:
    if path is None:
        env = os.environ if environ is None else environ
        raw = env.get("CTICONNECT_PATH")
        if not raw:
            raise CTIConnectUnavailable(
                "CTICONNECT_PATH is not set; clone the pinned CTIConnect repository outside this repository"
            )
        path = raw
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise CTIConnectUnavailable(f"CTICONNECT_PATH is not a directory: {root}")
    return root


def _git_revision(root: Path) -> str:
    if not (root / ".git").exists():
        raise CTIConnectAuditError(
            "CTIConnect checkout has no .git metadata; pinned external revision cannot be verified"
        )
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        raise CTIConnectAuditError("cannot read CTIConnect git revision")
    return completed.stdout.strip()


def _reject_dirty_required_inputs(root: Path) -> None:
    completed = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no", "--",
         "data", "corpus_kb", "corpus_reports", "cskg", "LICENSE", "LICENSE-DATA",
         "cticonnect/schema.py", "evaluation/metrics.py"],
        text=True, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        raise CTIConnectAuditError("cannot inspect CTIConnect worktree status")
    if completed.stdout.strip():
        raise CTIConnectAuditError("pinned CTIConnect benchmark inputs have local modifications")


def _task_path(root: Path, task: str, category: str) -> Path:
    return root / "data" / category / f"{task}.jsonl"


def audit_external_root(path: Path | str | None = None) -> AuditReport:
    root = resolve_external_root(path)
    revision = _git_revision(root)
    if revision != PINNED_COMMIT:
        raise CTIConnectAuditError(
            f"CTIConnect revision mismatch: expected {PINNED_COMMIT}, observed {revision}"
        )
    _reject_dirty_required_inputs(root)

    manifest_path = root / "data" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CTIConnectAuditError("CTIConnect data/manifest.json is unreadable") from exc
    if manifest.get("version") != PINNED_VERSION or manifest.get("total_count") != EXPECTED_TOTAL:
        raise CTIConnectAuditError("CTIConnect version/total count differs from pinned audit")
    if manifest.get("license_code") != "MIT" or manifest.get("license_data") != "CC-BY-4.0":
        raise CTIConnectAuditError("CTIConnect manifest license declarations changed")

    license_code = (root / "LICENSE").read_text(encoding="utf-8")
    license_data = (root / "LICENSE-DATA").read_text(encoding="utf-8")
    if "MIT License" not in license_code:
        raise CTIConnectAuditError("CTIConnect code license is not the audited MIT text")
    if "Creative Commons Attribution 4.0" not in license_data or "CC-BY-4.0" not in license_data:
        raise CTIConnectAuditError("CTIConnect data license is not the audited CC-BY-4.0 declaration")

    task_counts: dict[str, int] = {}
    task_hashes: dict[str, str] = {}
    for task, expected in EXPECTED_TASKS.items():
        declared = (manifest.get("tasks") or {}).get(task)
        if not isinstance(declared, dict):
            raise CTIConnectAuditError(f"missing task manifest entry: {task}")
        for field in ("category", "count", "eval_type", "target_type", "sha256"):
            expected_value = expected[field]
            if declared.get(field) != expected_value:
                raise CTIConnectAuditError(
                    f"task {task} field {field} changed: expected {expected_value!r}, observed {declared.get(field)!r}"
                )
        path_obj = _task_path(root, task, str(expected["category"]))
        observed_hash = _file_sha256(path_obj)
        observed_count = _nonempty_line_count(path_obj)
        if observed_hash != expected["sha256"] or observed_count != expected["count"]:
            raise CTIConnectAuditError(f"task {task} count/hash mismatch")
        task_counts[task] = observed_count
        task_hashes[task] = observed_hash
    if sum(task_counts.values()) != EXPECTED_TOTAL:
        raise CTIConnectAuditError("CTIConnect audited task counts do not sum to 1859")

    kb_manifest = json.loads((root / "corpus_kb" / "MANIFEST.json").read_text(encoding="utf-8"))
    kb_hashes: dict[str, str] = {}
    for name, expected in EXPECTED_KB_FILES.items():
        declared = (kb_manifest.get("files") or {}).get(name)
        if not isinstance(declared, dict):
            raise CTIConnectAuditError(f"missing structured corpus manifest entry: {name}")
        if declared.get("lines") != expected["lines"] or declared.get("sha256") != expected["sha256"]:
            raise CTIConnectAuditError(f"structured corpus manifest drift: {name}")
        corpus_path = root / "corpus_kb" / name
        observed_hash = _file_sha256(corpus_path)
        if observed_hash != expected["sha256"] or _nonempty_line_count(corpus_path) != expected["lines"]:
            raise CTIConnectAuditError(f"structured corpus count/hash mismatch: {name}")
        kb_hashes[name] = observed_hash

    reports = root / "corpus_reports" / "preprocessed_reports.jsonl"
    report_count = _nonempty_line_count(reports)
    if report_count != EXPECTED_REPORT_COUNT:
        raise CTIConnectAuditError(
            f"report corpus count mismatch: expected {EXPECTED_REPORT_COUNT}, observed {report_count}"
        )
    report_sha = _file_sha256(reports)

    graph_manifest_path = root / "cskg" / "manifest.json"
    graph_manifest = json.loads(graph_manifest_path.read_text(encoding="utf-8"))
    graph_assets = {
        "lineage": "extracted",
        "manifest_sha256": _file_sha256(graph_manifest_path),
        "n_reports_total": graph_manifest.get("n_reports_total"),
        "bm25_pickle_consumed": False,
    }
    return AuditReport(
        repository=PINNED_REPOSITORY,
        commit=revision,
        version=PINNED_VERSION,
        total_queries=EXPECTED_TOTAL,
        task_counts=task_counts,
        task_sha256=task_hashes,
        kb_sha256=kb_hashes,
        report_count=report_count,
        report_sha256=report_sha,
        code_license="MIT",
        data_license="CC-BY-4.0",
        graph_assets=graph_assets,
    )


def _parse_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CTIConnectAuditError(f"malformed JSONL {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise CTIConnectAuditError(f"non-object JSONL record {path}:{line_number}")
            yield value


def _nested_contents(record: Mapping[str, Any]) -> dict[str, Any]:
    contents = record.get("contents")
    if not isinstance(contents, str):
        raise CTIConnectAuditError("structured corpus record has no string contents field")
    try:
        nested = json.loads(contents)
    except json.JSONDecodeError as exc:
        raise CTIConnectAuditError("structured corpus contents is not valid nested JSON") from exc
    if not isinstance(nested, dict):
        raise CTIConnectAuditError("structured corpus contents must decode to an object")
    return nested


def _structured_identifier(kind: str, record: Mapping[str, Any]) -> str:
    fields = {"cve": "cve_id", "cwe": "cwe_id", "capec": "capec_id", "mitre": "mitre_id"}
    raw = record.get(fields[kind])
    if raw is None or not str(raw).strip():
        raise CTIConnectAuditError(f"{kind} record lacks its source identifier")
    value = str(raw).strip().upper()
    if kind == "cwe" and not value.startswith("CWE-"):
        value = f"CWE-{value}"
    elif kind == "capec" and not value.startswith("CAPEC-"):
        value = f"CAPEC-{value}"
    if kind == "cve" and not value.startswith("CVE-"):
        raise CTIConnectAuditError("cve_id is not a CVE identifier")
    if kind == "mitre" and not re.fullmatch(r"T\d{4}(?:\.\d{3})?", value):
        raise CTIConnectAuditError("mitre_id is not an ATT&CK technique identifier")
    return value


def parse_structured_record(kind: str, record: Mapping[str, Any], *, relative_path: str) -> CorpusDocument:
    if kind not in {"cve", "cwe", "capec", "mitre"}:
        raise ValueError(kind)
    source_identifier = _structured_identifier(kind, record)
    nested = _nested_contents(record)
    title = str(record.get("title") or source_identifier).strip()
    # Outer numeric IDs repeat across corpus files and are provenance only. Stable
    # source identity comes from cve_id/cwe_id/capec_id/mitre_id.
    outer_id = record.get("id")
    text = "\n".join(
        part for part in (
            source_identifier,
            title,
            json.dumps(nested, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
        ) if part
    )
    return CorpusDocument(
        document_id=f"{kind}:{source_identifier}",
        corpus_kind=kind,
        source_identifier=source_identifier,
        title=title,
        text=text,
        provenance={
            "source": kind,
            "relative_path": relative_path,
            "outer_id": None if outer_id is None else str(outer_id),
            "source_identifier": source_identifier,
            "nested_contents": True,
            "graph_lineage": False,
        },
    )


def parse_report_record(record: Mapping[str, Any], *, relative_path: str) -> CorpusDocument:
    if not isinstance(record.get("id"), int):
        raise CTIConnectAuditError("report id must be an integer for validated BLOG-id mapping")
    for field in ("title", "publish_date", "link", "preprocessed"):
        if not isinstance(record.get(field), str) or not str(record[field]).strip():
            raise CTIConnectAuditError(f"report record lacks required {field}")
    blog_id = f"BLOG-{record['id']}"
    title = str(record["title"]).strip()
    preprocessed = str(record["preprocessed"]).strip()
    return CorpusDocument(
        document_id=f"report:{blog_id}",
        corpus_kind="report",
        source_identifier=blog_id,
        title=title,
        text=f"{title}\n{preprocessed}",
        provenance={
            "source": "blog",
            "relative_path": relative_path,
            "blog_id": blog_id,
            "publish_date": str(record["publish_date"]),
            "link": str(record["link"]),
            "metadata": record.get("metadata") or {},
            "full_text_fetched": False,
            "graph_lineage": False,
        },
    )


def load_corpus(root: Path) -> tuple[CorpusDocument, ...]:
    documents: list[CorpusDocument] = []
    seen_ids: set[str] = set()
    for kind in ("cve", "cwe", "capec", "mitre"):
        relative = f"corpus_kb/{kind}.jsonl"
        for record in _parse_jsonl(root / relative):
            document = parse_structured_record(kind, record, relative_path=relative)
            if document.document_id in seen_ids:
                raise CTIConnectAuditError(f"duplicate stable corpus identifier: {document.document_id}")
            seen_ids.add(document.document_id)
            documents.append(document)
    report_relative = "corpus_reports/preprocessed_reports.jsonl"
    for record in _parse_jsonl(root / report_relative):
        document = parse_report_record(record, relative_path=report_relative)
        if document.document_id in seen_ids:
            raise CTIConnectAuditError(f"duplicate report identifier: {document.document_id}")
        seen_ids.add(document.document_id)
        documents.append(document)
    return tuple(documents)


def _official_label(record: Mapping[str, Any]) -> OfficialLabel:
    ground_truth = record.get("ground_truth")
    source = record.get("source")
    if not isinstance(ground_truth, dict) or not isinstance(source, dict):
        raise CTIConnectAuditError("benchmark record lacks ground_truth/source object")
    return OfficialLabel(
        query_id=str(record["id"]),
        task=str(record["task"]),
        eval_type=str(record["eval_type"]),
        target_type=str(ground_truth["target_type"]),
        target_id=ground_truth.get("target_id"),
        target_ids=tuple(str(x) for x in (ground_truth.get("target_ids") or ())),
        valid_target_ids=tuple(str(x) for x in (ground_truth.get("valid_target_ids") or ())),
        reference_answer=ground_truth.get("reference_answer"),
        source_type=str(source["source_type"]),
        source_id=source.get("source_id"),
        blog_ids=tuple(str(x) for x in (source.get("blog_ids") or ())),
        construction_file=source.get("construction_file"),
    )


def load_queries_and_labels(root: Path) -> tuple[tuple[QueryRecord, ...], dict[str, OfficialLabel]]:
    queries: list[QueryRecord] = []
    labels: dict[str, OfficialLabel] = {}
    for task, expected in EXPECTED_TASKS.items():
        for record in _parse_jsonl(_task_path(root, task, str(expected["category"]))):
            if record.get("task") != task or record.get("category") != expected["category"] or record.get("eval_type") != expected["eval_type"]:
                raise CTIConnectAuditError(f"task record schema drift: {record.get('id')}")
            query_id = str(record.get("id") or "")
            if not query_id or query_id in labels:
                raise CTIConnectAuditError("benchmark query IDs must be non-empty and unique")
            question = record.get("question")
            if not isinstance(question, str) or not question.strip():
                raise CTIConnectAuditError(f"benchmark record lacks question: {query_id}")
            # Query-only boundary: answers, ground truth, source clusters, and
            # construction provenance never enter QueryRecord/options.
            queries.append(QueryRecord(
                query_id=query_id,
                query=question,
                options={"task": task, "category": str(expected["category"]), "eval_type": str(expected["eval_type"])},
            ))
            labels[query_id] = _official_label(record)
    if len(queries) != EXPECTED_TOTAL or len(labels) != EXPECTED_TOTAL:
        raise CTIConnectAuditError("benchmark query count differs from pinned release")
    return tuple(queries), labels


def _canonical_identifier(kind: str, value: str) -> str:
    text = value.strip().upper()
    if kind == "mitre":
        match = re.search(r"T\s*\d{4}(?:\.\d{3})?", text)
        return match.group(0).replace(" ", "") if match else ""
    prefix = {"cve": "CVE", "cwe": "CWE", "capec": "CAPEC"}.get(kind)
    if prefix is None:
        return text
    if kind == "cve":
        match = re.search(r"CVE[\s-]*(\d{4})[\s-]*(\d{4,})", text)
        return f"CVE-{match.group(1)}-{match.group(2)}" if match else ""
    match = re.search(rf"{prefix}[\s-]*(\d+)", text)
    return f"{prefix}-{match.group(1)}" if match else ""


def extract_official_ids(text: str, kind: str) -> set[str]:
    pattern = _ID_PATTERNS.get(kind)
    if pattern is None or not text:
        return set()
    return {
        normalized
        for match in pattern.finditer(text)
        if (normalized := _canonical_identifier(kind, match.group(0)))
    }


def _prf1(pred: set[str], gold: set[str]) -> tuple[float, float, float]:
    if not pred and not gold:
        return 1.0, 1.0, 1.0
    if not pred or not gold:
        return 0.0, 0.0, 0.0
    intersection = len(pred & gold)
    precision = intersection / len(pred)
    recall = intersection / len(gold)
    return precision, recall, (2 * precision * recall / (precision + recall) if precision + recall else 0.0)


def official_identifier_score(prediction: str, label: OfficialLabel) -> OfficialItemScore:
    if label.eval_type not in {"single_id_match", "id_set_match"}:
        raise ValueError("official identifier score does not apply to judge tasks")
    kind = label.target_type
    canonical = ({label.target_id.upper()} if label.target_id else {x.upper() for x in label.target_ids})
    valid = canonical | {x.upper() for x in label.valid_target_ids}
    pred = {x.upper() for x in extract_official_ids(prediction, kind)}
    # Pinned official behavior: with alternates, any non-empty prediction entirely
    # inside the valid set earns full credit. Mixed valid/invalid output does not.
    if pred and pred <= valid and len(valid) > len(canonical):
        p = r = f1 = 1.0
        exact = True
    else:
        p, r, f1 = _prf1(pred, canonical)
        exact = pred == canonical
    return OfficialItemScore(
        precision=p, recall=r, f1=f1, exact_match=exact,
        pred_ids=tuple(sorted(pred)), canonical_gold_ids=tuple(sorted(canonical)), valid_ids=tuple(sorted(valid)),
    )


def target_document_ids(label: OfficialLabel) -> tuple[str, ...]:
    if label.eval_type == "judge" or label.target_type == "free_text":
        return ()
    values: list[str] = []
    if label.target_id:
        values.append(label.target_id)
    values.extend(label.target_ids)
    values.extend(label.valid_target_ids)
    prefix = {"cve": "cve", "cwe": "cwe", "capec": "capec", "mitre": "mitre"}.get(label.target_type)
    if prefix is None:
        return ()
    return tuple(dict.fromkeys(f"{prefix}:{str(value).upper()}" for value in values))


def source_proxy_document_ids(label: OfficialLabel) -> tuple[str, ...]:
    if label.source_type == "blog" and label.source_id:
        return (f"report:{label.source_id}",)
    if label.source_type == "blog_cluster":
        return tuple(f"report:{value}" for value in label.blog_ids)
    source_prefix = {"cve": "cve", "cwe": "cwe", "capec": "capec", "mitre": "mitre"}.get(label.source_type)
    if source_prefix and label.source_id:
        return (f"{source_prefix}:{label.source_id.upper()}",)
    return ()


def annotation_coverage(labels: Mapping[str, OfficialLabel], document_ids: set[str]) -> dict[str, Any]:
    target_total = target_mapped = source_total = source_mapped = 0
    exclusions: Counter[str] = Counter()
    for label in labels.values():
        target_ids = target_document_ids(label)
        if target_ids:
            target_total += 1
            if any(item in document_ids for item in target_ids):
                target_mapped += 1
            else:
                exclusions["unmapped_target"] += 1
        elif label.eval_type == "judge":
            exclusions["free_text_target_has_no_target_object_qrel"] += 1
        source_ids = source_proxy_document_ids(label)
        if source_ids:
            source_total += 1
            if all(item in document_ids for item in source_ids):
                source_mapped += 1
            else:
                exclusions["unmapped_source_proxy"] += 1
    return {
        "target_object_queries": target_total,
        "target_object_mapped": target_mapped,
        "target_object_coverage": (target_mapped / target_total if target_total else None),
        "source_proxy_queries": source_total,
        "source_proxy_mapped": source_mapped,
        "source_proxy_coverage": (source_mapped / source_total if source_total else None),
        "exclusion_reasons": dict(sorted(exclusions.items())),
        "source_proxy_semantics": "nonexhaustive retrieval proxy; not evidence/path ground truth",
    }


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in _TOKEN_RE.finditer(text))


class TextBM25:
    """Small deterministic BM25 rebuilt from text; no serialized index is trusted."""

    def __init__(self, documents: Sequence[CorpusDocument], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.documents = tuple(documents)
        self.k1 = k1
        self.b = b
        self.doc_tokens = [_tokens(doc.text) for doc in self.documents]
        self.lengths = [len(tokens) for tokens in self.doc_tokens]
        self.avgdl = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        self.df: Counter[str] = Counter()
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for index, tokens in enumerate(self.doc_tokens):
            counts = Counter(tokens)
            for token, frequency in counts.items():
                self.df[token] += 1
                self.postings[token].append((index, frequency))

    def search(self, query: str, *, top_k: int = 10, corpus_kind: str | None = None) -> tuple[str, ...]:
        query_terms = tuple(dict.fromkeys(_tokens(query)))
        scores: dict[int, float] = defaultdict(float)
        n_docs = len(self.documents)
        for term in query_terms:
            df = self.df.get(term, 0)
            if not df:
                continue
            idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
            for index, frequency in self.postings.get(term, ()):
                document = self.documents[index]
                if corpus_kind is not None and document.corpus_kind != corpus_kind:
                    continue
                dl = self.lengths[index]
                denominator = frequency + self.k1 * (
                    1.0 - self.b + self.b * dl / self.avgdl if self.avgdl else 1.0
                )
                scores[index] += idf * (frequency * (self.k1 + 1.0) / denominator)
        ranked = sorted(
            scores,
            key=lambda index: (-scores[index], self.documents[index].document_id),
        )
        return tuple(self.documents[index].document_id for index in ranked[:top_k])


def _groupings(queries: Sequence[QueryRecord], labels: Mapping[str, OfficialLabel]) -> tuple[QueryGrouping, ...]:
    rows: list[QueryGrouping] = []
    for query in queries:
        label = labels[query.query_id]
        source_ids = source_proxy_document_ids(label)
        cluster = "|".join(sorted(source_ids)) if source_ids else f"query:{query.query_id}"
        # Task + normalized source cluster is frozen before scoring. It uses source
        # provenance, never answer targets or reference answers.
        family = f"{label.task}:{cluster}"
        rows.append(QueryGrouping(query_id=query.query_id, object_cluster=cluster, near_duplicate_family=family))
    return tuple(rows)


def _metric_average(values: Sequence[MetricResult], reason: str) -> dict[str, Any]:
    applicable = [item for item in values if item.status == MetricStatus.OK and item.value is not None]
    if not applicable:
        return MetricResult(status=MetricStatus.NOT_APPLICABLE, reason=reason, support_count=0, annotation_coverage=0.0, value=None).model_dump(mode="json")
    return MetricResult(
        status=MetricStatus.OK,
        support_count=len(applicable),
        annotation_coverage=len(applicable) / len(values),
        value=sum(float(item.value) for item in applicable) / len(applicable),
    ).model_dump(mode="json")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def run_cticonnect_retrieval_experiment(*, config: Any, output: Path, external_root: Path | None = None) -> dict[str, Any]:
    root = resolve_external_root(external_root)
    audit = audit_external_root(root)
    documents = load_corpus(root)
    queries, labels = load_queries_and_labels(root)
    document_ids = {item.document_id for item in documents}
    coverage = annotation_coverage(labels, document_ids)
    frozen_split = grouped_split(_groupings(queries, labels), seed=20260918, dev_fraction=0.5)
    # Label boundary: everything above that informs retrieval uses questions/source
    # grouping only. Target/reference labels are first consumed below after the
    # corpus, split and lexical index are frozen.
    index = TextBM25(documents)
    per_query: list[dict[str, Any]] = []
    target_metrics: list[MetricResult] = []
    source_proxy_metrics: list[MetricResult] = []
    started_all = time.monotonic()
    for query in queries:
        started = time.monotonic()
        task = str(query.options["task"])
        ranking = index.search(query.query, top_k=10, corpus_kind=TASK_TARGET_CORPUS[task])
        label = labels[query.query_id]
        target_qrels = target_document_ids(label)
        source_proxy_qrels = source_proxy_document_ids(label)
        target_metric = recall_at_k(ranking, target_qrels, 10) if target_qrels else MetricResult(
            status=MetricStatus.NOT_APPLICABLE,
            reason="no target-object qrels for free-text synthesis task",
            support_count=0, annotation_coverage=0.0, value=None,
        )
        source_metric = recall_at_k(ranking, source_proxy_qrels, 10) if source_proxy_qrels else MetricResult(
            status=MetricStatus.NOT_APPLICABLE,
            reason="no source-proxy qrels for this query",
            support_count=0, annotation_coverage=0.0, value=None,
        )
        target_metrics.append(target_metric)
        source_proxy_metrics.append(source_metric)
        per_query.append({
            "query_id": query.query_id,
            "task": task,
            "query": query.query,
            "ranking": list(ranking),
            "latency_ms": (time.monotonic() - started) * 1000.0,
            "custom_retrieval": {
                "target_object_recall@10": target_metric.model_dump(mode="json"),
                "source_proxy_recall@10_nonexhaustive": source_metric.model_dump(mode="json"),
            },
        })

    output.mkdir(parents=True, exist_ok=True)
    config_snapshot = config.serializable_snapshot() if hasattr(config, "serializable_snapshot") else {}
    (output / "config.snapshot.yaml").write_text(yaml.safe_dump(config_snapshot, sort_keys=True), encoding="utf-8")
    _write_json(output / "environment.json", {
        "python": sys.version.split()[0],
        "network_used": False,
        "external_root_env": "CTICONNECT_PATH",
        "external_repository": PINNED_REPOSITORY,
        "external_commit": PINNED_COMMIT,
        "model_variants": {"status": "not_run", "reason": "no exact selected embedding/reranker/generator model configured for Prompt 18"},
        "throughput_claim": False,
    })
    _write_json(output / "corpus.manifest.snapshot.json", {
        "audit": asdict(audit),
        "document_count": len(documents),
        "structured_document_count": sum(1 for item in documents if item.corpus_kind != "report"),
        "report_document_count": sum(1 for item in documents if item.corpus_kind == "report"),
        "annotation_coverage": coverage,
        "graph_assets_consumed_for_retrieval": False,
        "serialized_cskg_bm25_consumed": False,
    })
    _write_json(output / "split.manifest.json", frozen_split.as_dict())
    (output / "per_query.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n" for item in per_query),
        encoding="utf-8",
    )
    retrieval_metrics = {
        "custom_metrics": {
            "target_object_recall@10": _metric_average(target_metrics, "no applicable target-object qrels"),
            "source_proxy_recall@10_nonexhaustive": _metric_average(source_proxy_metrics, "no applicable source proxy qrels"),
        },
        "official_metrics": {
            "status": "not_run",
            "reason": "official CTIConnect identifier/judge metrics require answer-model predictions; compatibility is golden-tested separately",
        },
        "qrels_semantics": {
            "target_object_mapping": "official target identifiers mapped to corpus documents where defined",
            "source_proxy": "nonexhaustive source-document proxy only; not evidence/path judgment",
        },
        "annotation_coverage": coverage,
    }
    _write_json(output / "retrieval_metrics.json", retrieval_metrics)
    _write_json(output / "answer_metrics.json", {
        "official_identifier_metrics": {"status": "not_run", "value": None, "reason": "no answer model configured"},
        "multi_doc_judge": {"status": "not_run", "value": None, "reason": "no independent judge/model configured"},
        "real_quality_promotion": {"status": "not_run", "value": None, "reason": "lexical external retrieval run alone cannot authorize promotion"},
    })
    latencies = [float(item["latency_ms"]) for item in per_query]
    _write_json(output / "latency_metrics.json", {
        "sample_count": len(latencies),
        "concurrency": 1,
        "mean_ms": sum(latencies) / len(latencies) if latencies else None,
        "max_ms": max(latencies) if latencies else None,
        "total_seconds": time.monotonic() - started_all,
        "throughput_reported": False,
    })
    report = [
        "# CTIConnect external retrieval experiment",
        "",
        f"- pinned repository: {PINNED_REPOSITORY}",
        f"- pinned commit: {PINNED_COMMIT}",
        f"- audited QA pairs: {audit.total_queries}",
        f"- corpus documents: {len(documents)}",
        "- retrieval: BM25 rebuilt from text; cskg/bm25_index.pkl was not loaded",
        "- query boundary: question + non-answer task metadata only",
        "- official answer metrics: not_run (no answer model configured)",
        "- selected model variants: not_run (no exact model/provider configured)",
        "- source qrels: nonexhaustive proxy, not evidence/path truth",
        "- graph assets: lineage audited as extracted; excluded from retrieval",
        "- quality promotion: not_run",
        "",
        "Data are external and remain under CTIConnect CC-BY-4.0; this repository vendors no benchmark corpus.",
    ]
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return {
        "schema_version": "cticonnect-retrieval-experiment-v1",
        "output": str(output),
        "queries": len(per_query),
        "external_commit": PINNED_COMMIT,
        "network_used": False,
        "real_quality": "not_run",
    }


__all__ = [
    "AuditReport", "CTIConnectAuditError", "CTIConnectError", "CTIConnectUnavailable",
    "CorpusDocument", "OfficialItemScore", "OfficialLabel", "PINNED_COMMIT",
    "EXPECTED_TASKS", "EXPECTED_TOTAL", "TextBM25", "annotation_coverage",
    "audit_external_root", "extract_official_ids", "load_corpus", "load_queries_and_labels",
    "official_identifier_score", "parse_report_record", "parse_structured_record",
    "resolve_external_root", "run_cticonnect_retrieval_experiment",
    "source_proxy_document_ids", "target_document_ids",
]
