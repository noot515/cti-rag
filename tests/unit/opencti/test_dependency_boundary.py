from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.integrations.opencti.client import OpenCTIReadError, create_live_transport


ROOT = Path(__file__).resolve().parents[3]


def _requirement_lines(name: str) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def test_pycti_is_lazy_and_optional_for_offline_import(monkeypatch: pytest.MonkeyPatch):
    real_import_module = importlib.import_module

    def guarded_import(name: str, package: str | None = None):
        if name == "pycti":
            raise ImportError("pycti deliberately unavailable in offline validation")
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", guarded_import)

    config = SimpleNamespace(
        token_env="OPENCTI_API_TOKEN",
        expected_client_version="7.260914.0",
    )
    with pytest.raises(OpenCTIReadError, match=r"pycti==7\.260914\.0"):
        create_live_transport(
            config,
            environ={"OPENCTI_API_TOKEN": "validation-only-token"},
        )


def test_offline_validation_profile_excludes_live_pycti():
    lines = _requirement_lines("requirements-advanced-validation.txt")

    assert "-r requirements-advanced-dev.txt" in lines
    assert "-r requirements-advanced-services.txt" in lines
    assert not any(line.startswith("pycti") for line in lines)


def test_live_opencti_profile_is_separate_from_application_api_profile():
    lines = _requirement_lines("requirements-advanced-opencti.txt")

    assert "-r requirements-advanced.txt" in lines
    assert "pycti==7.260914.0" in lines
    assert "-r requirements-advanced-api.txt" not in lines
    assert "-r requirements-advanced-dev.txt" not in lines
