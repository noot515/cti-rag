"""Collection policy for legacy tests that require external services."""

from __future__ import annotations

from pathlib import Path

import pytest


_INTEGRATION_FILES = {
    "model_router_test.py",
    "test_redis_runtime.py",
    "test_redis_session.py",
}

_LEGACY_SERVICE_FILES = {
    "test_original_error.py",
}


def pytest_collection_modifyitems(items):
    for item in items:
        name = Path(str(item.path)).name
        if name in _INTEGRATION_FILES:
            item.add_marker(pytest.mark.integration)
        if name in _LEGACY_SERVICE_FILES:
            item.add_marker(pytest.mark.legacy_service)
