"""Evaluation data-boundary contracts for advanced RAG baselines."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvaluationDataError(ValueError):
    pass


class EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, str_strip_whitespace=True)


class SourceLineage(EvalModel):
    source_name: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    license_or_terms: str = Field(min_length=1)
    public_or_sanitized: bool


class CorpusFile(EvalModel):
    role: Literal["corpus"] = "corpus"
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: str = Field(min_length=1)
    lineage: SourceLineage

    @field_validator("path")
    @classmethod
    def relative_safe_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("manifest paths must use repository-relative POSIX separators")
        path = PurePosixPath(value)
        if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
            raise ValueError("manifest path must be a normalized repository-relative path")
        return value


class CorpusManifest(EvalModel):
    schema_version: Literal["corpus-manifest-v1"] = "corpus-manifest-v1"
    corpus_id: str = Field(min_length=1)
    files: tuple[CorpusFile, ...]

    @model_validator(mode="after")
    def require_files(self) -> "CorpusManifest":
        if not self.files:
            raise ValueError("corpus manifest must contain at least one corpus file")
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("corpus manifest paths must be unique")
        if not all(item.lineage.public_or_sanitized for item in self.files):
            raise ValueError("baseline corpus files must be explicitly public or sanitized")
        return self


class QueryRecord(EvalModel):
    schema_version: Literal["query-record-v1"] = "query-record-v1"
    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1, max_length=8192)
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("options")
    @classmethod
    def reject_evaluation_only_options(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = {"answer", "ground_truth", "ground_truth_answer", "expected_answer", "qrels", "label", "relevance"}

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                keys = {str(key).lower() for key in node}
                hit = keys & forbidden
                if hit:
                    raise ValueError(f"evaluation-only field is not allowed in query options: {sorted(hit)[0]}")
                for item in node.values():
                    walk(item)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(value)
        return value


class QrelRecord(EvalModel):
    schema_version: Literal["qrel-record-v1"] = "qrel-record-v1"
    query_id: str = Field(min_length=1)
    target_object_uid: str = Field(pattern=r"^[0-9a-f]{64}$")
    relevance: int = Field(ge=0, le=3)


class AnnotationRecord(EvalModel):
    schema_version: Literal["annotation-record-v1"] = "annotation-record-v1"
    query_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: Any
    annotator: str = Field(min_length=1)


_QA_QUERY_KEYS = {"query", "question", "prompt", "instruction"}
_QA_LABEL_KEYS = {"answer", "ground_truth", "ground_truth_answer", "expected_answer", "qrels", "label", "relevance"}


def _looks_like_qa_payload(value: Any) -> bool:
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        if keys & _QA_QUERY_KEYS and keys & _QA_LABEL_KEYS:
            return True
        return any(_looks_like_qa_payload(item) for item in value.values())
    if isinstance(value, list):
        return any(_looks_like_qa_payload(item) for item in value)
    return False


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_fingerprint(manifest: CorpusManifest) -> str:
    payload = manifest.model_dump_json(exclude_none=False).encode("utf-8")
    return sha256(payload).hexdigest()


def load_corpus_manifest(path: Path) -> CorpusManifest:
    try:
        return CorpusManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise EvaluationDataError(f"invalid corpus manifest: {path}") from exc


def validate_corpus_manifest(manifest: CorpusManifest, repo_root: Path) -> tuple[Path, ...]:
    root = repo_root.resolve()
    validated: list[Path] = []
    for entry in manifest.files:
        candidate = (root / entry.path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise EvaluationDataError(f"corpus path escapes repository root: {entry.path}") from exc
        if not candidate.is_file():
            raise EvaluationDataError(f"corpus file does not exist: {entry.path}")
        observed = file_sha256(candidate)
        if observed != entry.sha256:
            raise EvaluationDataError(
                f"corpus file hash mismatch for {entry.path}: expected {entry.sha256}, observed {observed}"
            )
        if candidate.suffix.lower() in {".json", ".jsonl"}:
            try:
                if candidate.suffix.lower() == ".json":
                    payload = json.loads(candidate.read_text(encoding="utf-8"))
                    if not isinstance(payload, dict) or payload.get("schema_version") != entry.schema_version:
                        raise EvaluationDataError(f"corpus schema_version mismatch for {entry.path}")
                    if _looks_like_qa_payload(payload):
                        raise EvaluationDataError(f"QA-shaped data cannot be used as corpus input: {entry.path}")
                else:
                    for line in candidate.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        record = json.loads(line)
                        if not isinstance(record, dict) or record.get("schema_version") != entry.schema_version:
                            raise EvaluationDataError(f"corpus schema_version mismatch for {entry.path}")
                        if _looks_like_qa_payload(record):
                            raise EvaluationDataError(f"QA-shaped data cannot be used as corpus input: {entry.path}")
            except json.JSONDecodeError as exc:
                raise EvaluationDataError(f"invalid JSON corpus file: {entry.path}") from exc
        validated.append(candidate)
    return tuple(validated)


def load_query_records(path: Path) -> tuple[QueryRecord, ...]:
    try:
        if path.suffix.lower() == ".jsonl":
            records = [QueryRecord.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise EvaluationDataError("query manifest must contain a JSON list or JSONL records")
            records = [QueryRecord.model_validate(item) for item in payload]
    except EvaluationDataError:
        raise
    except Exception as exc:
        raise EvaluationDataError(f"invalid query records: {path}") from exc
    ids = [record.query_id for record in records]
    if not records or len(ids) != len(set(ids)):
        raise EvaluationDataError("query manifest must contain non-empty unique query_id values")
    return tuple(records)


__all__ = [
    "AnnotationRecord", "CorpusFile", "CorpusManifest", "EvaluationDataError", "QrelRecord", "QueryRecord",
    "SourceLineage", "file_sha256", "load_corpus_manifest", "load_query_records", "manifest_fingerprint",
    "validate_corpus_manifest",
]
