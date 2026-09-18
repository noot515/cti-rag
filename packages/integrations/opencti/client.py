"""Narrow read-only OpenCTI client boundary.

Only this module imports and instantiates OpenCTIApiClient. Higher layers depend
on the OpenCTIPageTransport protocol from reader.py and therefore cannot acquire
mutation-capable OpenCTI objects by accident.
"""
from __future__ import annotations

import importlib
import os
from typing import Any, Mapping


SUPPORTED_OPENCTI_VERSION = "7.260914.0"
SUPPORTED_PYCTI_VERSION = "7.260914.0"


class OpenCTIReadError(RuntimeError):
    pass


class OpenCTIAccessError(OpenCTIReadError):
    pass


class OpenCTITransientReadError(OpenCTIReadError):
    pass


class OpenCTIVersionMismatch(OpenCTIReadError):
    pass


def _translate_error(exc: Exception) -> OpenCTIReadError:
    message = str(exc)
    folded = message.casefold()
    name = type(exc).__name__.casefold()
    if any(token in folded for token in ("401", "403", "unauthorized", "forbidden", "access denied")):
        return OpenCTIAccessError("OpenCTI read credential is unauthorized or forbidden")
    if any(token in name for token in ("timeout", "connection")) or any(
        token in folded for token in ("timed out", "timeout", "connection reset", "temporarily unavailable", "503", "502", "504")
    ):
        return OpenCTITransientReadError("transient OpenCTI read failure")
    return OpenCTIReadError(f"OpenCTI read failed: {type(exc).__name__}")


class LiveOpenCTIReadTransport:
    """Expose only bounded list operations from a version-checked pycti client."""

    _ENTITY_ATTR = {
        "attack_pattern": "attack_pattern",
        "vulnerability": "vulnerability",
        "report": "report",
        "relationship": "stix_core_relationship",
    }

    def __init__(self, api: Any, *, platform_version: str) -> None:
        self._api = api
        self.platform_version = platform_version

    def list_page(
        self,
        kind: str,
        *,
        filters: Mapping[str, Any] | None,
        first: int,
        after: str | None,
    ) -> dict[str, Any]:
        if kind not in self._ENTITY_ATTR:
            raise ValueError(f"unsupported OpenCTI capture kind: {kind}")
        if first < 1 or first > 200:
            raise ValueError("OpenCTI page size must be in [1, 200]")
        entity = getattr(self._api, self._ENTITY_ATTR[kind])
        try:
            result = entity.list(
                filters=dict(filters) if filters else None,
                first=first,
                after=after,
                orderBy="updated_at",
                orderMode="asc",
                withPagination=True,
                getAll=False,
            )
        except Exception as exc:
            raise _translate_error(exc) from exc
        if not isinstance(result, dict):
            raise OpenCTIReadError("pycti pagination result is not an object")
        entities = result.get("entities")
        pagination = result.get("pagination")
        if not isinstance(entities, list) or not isinstance(pagination, dict):
            raise OpenCTIReadError("pycti pagination result lacks entities/pagination")
        return {"entities": entities, "pagination": pagination}


def create_live_transport(config: Any, *, environ: Mapping[str, str] | None = None) -> LiveOpenCTIReadTransport:
    """Create the only SDK object, then expose a read-only wrapper."""
    env = os.environ if environ is None else environ
    token = env.get(config.token_env)
    if not token:
        raise OpenCTIAccessError(
            f"OpenCTI token environment variable {config.token_env!r} is not set"
        )

    try:
        pycti = importlib.import_module("pycti")
    except ImportError as exc:
        raise OpenCTIReadError(
            f"pycti=={config.expected_client_version} is required for live OpenCTI mode"
        ) from exc

    observed_client = str(getattr(pycti, "__version__", "unknown"))
    if observed_client != config.expected_client_version:
        raise OpenCTIVersionMismatch(
            f"pycti version mismatch: expected {config.expected_client_version}, observed {observed_client}"
        )
    if config.expected_client_version != SUPPORTED_PYCTI_VERSION:
        raise OpenCTIVersionMismatch(
            f"unsupported pycti version for Prompt 19: {config.expected_client_version}"
        )

    try:
        api = pycti.OpenCTIApiClient(
            config.api_url,
            token,
            ssl_verify=True,
            perform_health_check=False,
            requests_timeout=max(1, int(config.timeout_seconds)),
            provider="cti-rag-readonly",
        )
        response = api.query("query CtiRagAbout { about { version } }")
    except Exception as exc:
        raise _translate_error(exc) from exc

    try:
        platform_version = str(response["data"]["about"]["version"])
    except (KeyError, TypeError) as exc:
        raise OpenCTIReadError("OpenCTI about query did not return a version") from exc
    if platform_version != config.expected_platform_version:
        raise OpenCTIVersionMismatch(
            f"OpenCTI platform version mismatch: expected {config.expected_platform_version}, observed {platform_version}"
        )
    if config.expected_platform_version != SUPPORTED_OPENCTI_VERSION:
        raise OpenCTIVersionMismatch(
            f"unsupported OpenCTI platform version for Prompt 19: {config.expected_platform_version}"
        )
    return LiveOpenCTIReadTransport(api, platform_version=platform_version)


__all__ = [
    "LiveOpenCTIReadTransport",
    "OpenCTIAccessError",
    "OpenCTIReadError",
    "OpenCTITransientReadError",
    "OpenCTIVersionMismatch",
    "SUPPORTED_OPENCTI_VERSION",
    "SUPPORTED_PYCTI_VERSION",
    "create_live_transport",
]
