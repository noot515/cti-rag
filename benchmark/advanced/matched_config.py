"""Strict configuration for Prompt 22 matched-corpus release evaluation."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import math
from pathlib import Path
from typing import Any
import yaml

SCHEMA_VERSION = "matched-corpus-config-v1"
GATE_VALUES = frozenset({"pass", "fail", "not_run", "not_comparable", "inconclusive"})
REQUIRED_RELEASE_GATES = frozenset({"rollback_mechanics", "predecessor_correctness", "real_opencti", "real_milvus", "real_neo4j", "backend_isolation", "secret_handling", "freshness_lifecycle", "judged_quality", "deployment_authorization"})

class MatchedCorpusError(RuntimeError): pass

@dataclass(frozen=True)
class QuerySpec:
    query_id: str
    text: str
    namespace: str | None = None
    value: str | None = None

@dataclass(frozen=True)
class MatchedConfig:
    opencti_config: Path
    direct_source_instance: str
    direct_scope_id: str
    direct_label: str
    ingestion_label: str
    queries: tuple[QuerySpec, ...]
    top_k: int
    pre_rerank_limit: int
    context_budget: int
    lexical_k1: float
    lexical_b: float
    score_abs_tolerance: float
    rank_mismatch_tolerance: int
    cold_repeats: int
    warm_repeats: int
    ann_settings: dict[str, Any]
    models: dict[str, Any]
    quality: dict[str, Any]
    release: dict[str, str]
    enriched_report: Path | None
    extraction: dict[str, Any]

def repo_root() -> Path: return Path(__file__).resolve().parents[2]
def resolve(path: Path | str) -> Path:
    value = Path(path); return value if value.is_absolute() else (repo_root() / value).resolve()
def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()
def gate(value: Any, name: str) -> str:
    value = str(value)
    if value not in GATE_VALUES: raise MatchedCorpusError(f"unsupported release gate {name}={value!r}")
    return value

def load_config(path: Path | str) -> MatchedConfig:
    try: raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc: raise MatchedCorpusError("matched-corpus configuration is unreadable") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION: raise MatchedCorpusError(f"matched-corpus config must use {SCHEMA_VERSION}")
    comparison, retrieval, operational = raw.get("comparison") or {}, raw.get("retrieval") or {}, raw.get("operational") or {}
    quality, release, extraction, models = raw.get("quality") or {}, raw.get("release_evidence") or {}, raw.get("extraction") or {}, raw.get("models") or {}
    if not all(isinstance(x, dict) for x in (comparison, retrieval, operational, quality, release, extraction, models)): raise MatchedCorpusError("configuration sections must be mappings")
    queries = []
    for item in raw.get("queries") or ():
        exact = item.get("exact") or {}; queries.append(QuerySpec(str(item["id"]), str(item["text"]), exact.get("namespace"), exact.get("value")))
    if not queries or len({q.query_id for q in queries}) != len(queries): raise MatchedCorpusError("queries must be nonempty with unique IDs")
    top_k, pre, context = int(retrieval.get("top_k", 12)), int(retrieval.get("pre_rerank_limit", 60)), int(retrieval.get("context_budget", 8000))
    if not 1 <= top_k <= 50 or pre != 60 or context != 8000: raise MatchedCorpusError("fixed release budgets require top_k<=50, pre_rerank=60, context=8000")
    lexical = retrieval.get("lexical") or {}; k1, b = float(lexical.get("k1", 1.5)), float(lexical.get("b", .75))
    if not math.isclose(k1, 1.5, abs_tol=1e-12) or not math.isclose(b, .75, abs_tol=1e-12): raise MatchedCorpusError("matched comparison requires BM25 k1=1.5,b=0.75")
    ann = dict(retrieval.get("ann") or {})
    if "enabled" not in ann or not models: raise MatchedCorpusError("ANN and model settings must be explicit")
    missing = REQUIRED_RELEASE_GATES - set(release)
    if missing: raise MatchedCorpusError(f"missing release gates: {sorted(missing)}")
    release = {name: gate(release[name], name) for name in sorted(REQUIRED_RELEASE_GATES)}
    enriched = raw.get("enriched_experiment") or {}; report = enriched.get("report") if isinstance(enriched, dict) else None
    return MatchedConfig(Path(str(comparison["opencti_config"])), str(comparison.get("direct_source_instance") or "matched-c1-direct"), str(comparison.get("direct_scope_id") or "matched-c1-direct"), str(comparison.get("direct_label") or "C1-direct"), str(comparison.get("ingestion_label") or "I1-opencti"), tuple(queries), top_k, pre, context, k1, b, float(retrieval.get("score_abs_tolerance", 1e-12)), int(retrieval.get("rank_mismatch_tolerance", 0)), int(operational.get("cold_repeats", 2)), int(operational.get("warm_repeats", 5)), ann, dict(models), dict(quality), release, None if report in {None, ""} else Path(str(report)), dict(extraction))

__all__ = ["MatchedConfig", "MatchedCorpusError", "QuerySpec", "file_sha256", "gate", "load_config", "repo_root", "resolve"]
