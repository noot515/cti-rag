"""Pure validated configuration for the advanced evidence/RAG path.

This module is intentionally safe to import in an offline process. It does not load
``.env`` files, construct providers, inspect model directories, create state, or
open network connections.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Callable, Literal, Mapping
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, ValidationError, field_validator, model_validator

from .validation import require_sha256


class AdvancedRagConfigError(ValueError):
    """Raised when an advanced RAG configuration cannot be validated."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceScopeConfig(_StrictModel):
    corpus_id: str = Field(default="fixture-cti", min_length=1)
    scope_id: str = Field(default="public-fixture", min_length=1)
    source_allowlist: tuple[str, ...] = ("fixture-public",)


class ChannelConfig(_StrictModel):
    exact_enabled: StrictBool = True
    lexical_enabled: StrictBool = True
    dense_enabled: StrictBool = True
    graph_enabled: StrictBool = True
    exact_top_k: StrictInt = Field(default=10, ge=1, le=50)
    lexical_top_k: StrictInt = Field(default=40, ge=1, le=50)
    dense_top_k: StrictInt = Field(default=40, ge=1, le=50)
    graph_top_k: StrictInt = Field(default=40, ge=1, le=50)


class GraphConfig(_StrictModel):
    max_hops: StrictInt = Field(default=2, ge=0, le=3)
    max_mapping_hops: StrictInt = Field(default=3, ge=0, le=3)
    seed_limit: StrictInt = Field(default=8, ge=1, le=50)
    neighbor_limit: StrictInt = Field(default=30, ge=1, le=50)
    path_limit: StrictInt = Field(default=40, ge=1, le=50)
    max_visited_nodes: StrictInt = Field(default=1000, ge=1)


class RerankerConfig(_StrictModel):
    enabled: StrictBool = False
    top_k: StrictInt = Field(default=60, ge=1, le=60)
    provider: str = Field(default="disabled", min_length=1)
    model: str = Field(default="disabled", min_length=1)
    remote: StrictBool = False


class ContextConfig(_StrictModel):
    max_tokens: StrictInt = Field(default=8000, ge=1)
    reserve_tokens: StrictInt = Field(default=512, ge=0)
    max_items: StrictInt = Field(default=15, ge=1, le=50)

    @model_validator(mode="after")
    def reserve_fits_budget(self) -> "ContextConfig":
        if self.reserve_tokens > self.max_tokens:
            raise ValueError("reserve_tokens must not exceed max_tokens")
        return self


class ProviderFingerprint(_StrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    dimension: StrictInt = Field(ge=1)
    metric: Literal["cosine", "ip", "l2"] = "cosine"
    normalization: Literal["none", "l2"] = "none"
    document_instruction: str = ""
    query_instruction: str = ""
    tokenizer: str = Field(default="unspecified", min_length=1)
    artifact_sha256: str | None = None
    remote: StrictBool = False

    @field_validator("artifact_sha256")
    @classmethod
    def validate_artifact_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_sha256(value, field_name="artifact_sha256")


class ProviderConfig(_StrictModel):
    embedding: ProviderFingerprint = Field(
        default_factory=lambda: ProviderFingerprint(
            provider="fixture",
            model="deterministic-hash-embedding",
            revision="v1",
            dimension=64,
            metric="cosine",
            normalization="l2",
            document_instruction="fixture-document",
            query_instruction="fixture-query",
            tokenizer="utf8-bytes-sha256-v1",
            artifact_sha256="3fc40254c00d381abc6f2fc6d23fd0e833725ae5a47bd19e0fe4f743755e17e9",
            remote=False,
        )
    )
    reranker: ProviderFingerprint | None = None


class PolicyConfig(_StrictModel):
    policy_version: str = Field(default="public-fixture-v1", min_length=1)
    public_fixture_sources: tuple[str, ...] = ("fixture-public",)
    allow_remote_destinations: StrictBool = False
    allow_privileged_debug: StrictBool = False


class TimeoutConfig(_StrictModel):
    request_seconds: StrictFloat = Field(default=10.0, gt=0)
    channel_seconds: StrictFloat = Field(default=3.0, gt=0)
    reranker_seconds: StrictFloat = Field(default=4.0, gt=0)


class MilvusServiceConfig(_StrictModel):
    enabled: StrictBool = False
    uri: str = Field(default="http://127.0.0.1:19531", min_length=1)
    deployment_id: str = Field(default="advanced-local", min_length=1)
    collection_prefix: str = Field(default="adv_cti", min_length=1, max_length=48)
    expected_server_version: str = Field(default="2.3.4", min_length=1)
    expected_client_version: str = Field(default="2.3.7", min_length=1)
    token_env: str | None = None

    @model_validator(mode="after")
    def validate_advanced_endpoint(self) -> "MilvusServiceConfig":
        parsed = urlparse(self.uri)
        if parsed.scheme not in {"http", "https", "tcp"} or not parsed.hostname:
            raise ValueError("advanced Milvus URI must be an explicit http/https/tcp endpoint")
        if not self.deployment_id.startswith("advanced-"):
            raise ValueError("Milvus deployment_id must identify an advanced deployment")
        if self.collection_prefix.startswith(("kb_", "legacy_")):
            raise ValueError("advanced Milvus collection prefix cannot use a legacy namespace")
        if self.token_env is not None and not self.token_env.strip():
            raise ValueError("Milvus token_env must be a non-empty environment variable name")
        return self


class NetworkConfig(_StrictModel):
    allow_outbound: StrictBool = False
    allow_downloads: StrictBool = False
    web_search: StrictBool = False


class AdvancedRagConfig(_StrictModel):
    schema_version: Literal["advanced-rag-config-v1"] = "advanced-rag-config-v1"
    enabled: StrictBool = False
    profile: Literal["fixture", "services", "opencti"] = "fixture"
    state_dir: str = Field(default="saves/advanced", min_length=1)
    source: SourceScopeConfig = Field(default_factory=SourceScopeConfig)
    channels: ChannelConfig = Field(default_factory=ChannelConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    providers: ProviderConfig = Field(default_factory=ProviderConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    milvus: MilvusServiceConfig = Field(default_factory=MilvusServiceConfig)

    @model_validator(mode="after")
    def enforce_profile_invariants(self) -> "AdvancedRagConfig":
        if self.profile == "fixture":
            if self.network.allow_outbound or self.network.allow_downloads or self.network.web_search:
                raise ValueError("fixture profile forbids outbound networking, downloads, and web search")
            if self.providers.embedding.remote:
                raise ValueError("fixture profile requires a local embedding provider")
            if self.providers.reranker is not None and self.providers.reranker.remote:
                raise ValueError("fixture profile requires a local reranker provider")
            if self.reranker.remote:
                raise ValueError("fixture profile cannot select a remote reranker")
            if self.milvus.enabled:
                raise ValueError("fixture profile cannot connect to the Milvus services backend")
        return self

    def serializable_snapshot(self) -> dict[str, Any]:
        """Return a deterministic secret-free configuration snapshot."""
        return self.model_dump(mode="json")


@dataclass(frozen=True)
class RuntimeFactories:
    """Injected constructors for runtime-only integrations.

    Storing callables here is inert. No factory is called by configuration parsing.
    """

    embedding_factory: Callable[[], Any] | None = None
    reranker_factory: Callable[[], Any] | None = None
    graph_factory: Callable[[], Any] | None = None
    opencti_factory: Callable[[], Any] | None = None
    web_factory: Callable[[], Any] | None = None

    def validate_for(self, config: AdvancedRagConfig) -> None:
        if config.profile == "fixture" and (self.opencti_factory is not None or self.web_factory is not None):
            raise AdvancedRagConfigError(
                "fixture profile cannot receive OpenCTI or web runtime factories"
            )


_ENV_OVERRIDES: dict[str, tuple[tuple[str, ...], Callable[[str], Any]]] = {
    "ADVANCED_RAG_ENABLED": (("enabled",), lambda value: _parse_bool("ADVANCED_RAG_ENABLED", value)),
    "ADVANCED_RAG_PROFILE": (("profile",), str),
    "ADVANCED_RAG_STATE_DIR": (("state_dir",), str),
    "ADVANCED_RAG_EXACT_TOP_K": (("channels", "exact_top_k"), lambda value: _parse_int("ADVANCED_RAG_EXACT_TOP_K", value)),
    "ADVANCED_RAG_LEXICAL_TOP_K": (("channels", "lexical_top_k"), lambda value: _parse_int("ADVANCED_RAG_LEXICAL_TOP_K", value)),
    "ADVANCED_RAG_DENSE_TOP_K": (("channels", "dense_top_k"), lambda value: _parse_int("ADVANCED_RAG_DENSE_TOP_K", value)),
    "ADVANCED_RAG_GRAPH_TOP_K": (("channels", "graph_top_k"), lambda value: _parse_int("ADVANCED_RAG_GRAPH_TOP_K", value)),
    "ADVANCED_RAG_GRAPH_MAX_HOPS": (("graph", "max_hops"), lambda value: _parse_int("ADVANCED_RAG_GRAPH_MAX_HOPS", value)),
    "ADVANCED_RAG_REQUEST_TIMEOUT_SECONDS": (("timeouts", "request_seconds"), lambda value: _parse_float("ADVANCED_RAG_REQUEST_TIMEOUT_SECONDS", value)),
    "ADVANCED_RAG_CHANNEL_TIMEOUT_SECONDS": (("timeouts", "channel_seconds"), lambda value: _parse_float("ADVANCED_RAG_CHANNEL_TIMEOUT_SECONDS", value)),
    "ADVANCED_RAG_MILVUS_ENABLED": (("milvus", "enabled"), lambda value: _parse_bool("ADVANCED_RAG_MILVUS_ENABLED", value)),
    "ADVANCED_RAG_MILVUS_URI": (("milvus", "uri"), str),
    "ADVANCED_RAG_MILVUS_DEPLOYMENT_ID": (("milvus", "deployment_id"), str),
    "ADVANCED_RAG_MILVUS_COLLECTION_PREFIX": (("milvus", "collection_prefix"), str),
    "ADVANCED_RAG_MILVUS_TOKEN_ENV": (("milvus", "token_env"), str),
}


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise AdvancedRagConfigError(
        f"{name} must be one of true/false, 1/0, yes/no, or on/off"
    )


def _parse_int(name: str, value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise AdvancedRagConfigError(f"{name} must be an integer") from exc


def _parse_float(name: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise AdvancedRagConfigError(f"{name} must be a number") from exc


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _set_nested(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = target
    for segment in path[:-1]:
        current = cursor.get(segment)
        if current is None:
            current = {}
            cursor[segment] = current
        if not isinstance(current, dict):
            raise AdvancedRagConfigError(
                f"cannot apply environment override below non-object field {segment!r}"
            )
        cursor = current
    cursor[path[-1]] = value


def _load_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AdvancedRagConfigError(f"advanced RAG configuration file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AdvancedRagConfigError(f"cannot read advanced RAG configuration file: {path}") from exc

    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(text) if text.strip() else {}
        elif path.suffix.lower() in {".yaml", ".yml"}:
            payload = yaml.safe_load(text) if text.strip() else {}
        else:
            raise AdvancedRagConfigError("advanced RAG config must be .json, .yaml, or .yml")
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise AdvancedRagConfigError(f"invalid advanced RAG configuration syntax: {path}") from exc

    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise AdvancedRagConfigError("advanced RAG configuration root must be an object")
    return payload


def load_advanced_rag_config(
    path: str | os.PathLike[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    trusted_overrides: Mapping[str, Any] | None = None,
) -> AdvancedRagConfig:
    """Load configuration using explicit precedence and post-merge invariants.

    Precedence is: model defaults < selected file < documented ADVANCED_RAG_*
    environment overrides < trusted application overrides. The fixture profile's
    no-network rules are validated after all merging, so environment variables such
    as TAVILY_API_KEY cannot re-enable web access.
    """

    merged: dict[str, Any] = {}
    if path is not None:
        merged = _deep_merge(merged, _load_file(Path(path)))

    env = os.environ if environ is None else environ
    env_patch: dict[str, Any] = {}
    for name, (field_path, parser) in _ENV_OVERRIDES.items():
        if name in env:
            _set_nested(env_patch, field_path, parser(env[name]))
    merged = _deep_merge(merged, env_patch)

    if trusted_overrides is not None:
        if not isinstance(trusted_overrides, Mapping):
            raise AdvancedRagConfigError("trusted_overrides must be a mapping")
        merged = _deep_merge(merged, trusted_overrides)

    try:
        return AdvancedRagConfig.model_validate(merged)
    except ValidationError as exc:
        raise AdvancedRagConfigError(str(exc)) from exc


__all__ = [
    "AdvancedRagConfig",
    "AdvancedRagConfigError",
    "ChannelConfig",
    "ContextConfig",
    "GraphConfig",
    "MilvusServiceConfig",
    "NetworkConfig",
    "PolicyConfig",
    "ProviderConfig",
    "ProviderFingerprint",
    "RerankerConfig",
    "RuntimeFactories",
    "SourceScopeConfig",
    "TimeoutConfig",
    "load_advanced_rag_config",
]
