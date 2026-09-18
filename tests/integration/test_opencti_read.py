from __future__ import annotations

import os

import pytest

from packages.evidence.config import OpenCTIServiceConfig
from packages.integrations.opencti.client import create_live_transport


pytestmark = [pytest.mark.integration, pytest.mark.opencti]


def test_live_opencti_read_is_bounded_and_read_only():
    if os.environ.get("OPENCTI_TEST_LIVE") != "1":
        pytest.skip("OPENCTI_TEST_LIVE=1 is required for the live read-only gate")
    url = os.environ.get("OPENCTI_API_URL")
    token = os.environ.get("OPENCTI_API_TOKEN")
    if not url or not token:
        pytest.skip("OPENCTI_API_URL and OPENCTI_API_TOKEN are required")

    config = OpenCTIServiceConfig(
        enabled=True,
        mode="live",
        api_url=url,
        token_env="OPENCTI_API_TOKEN",
        expected_platform_version=os.environ.get("OPENCTI_EXPECTED_VERSION", "7.260914.0"),
        expected_client_version="7.260914.0",
        source_instance="opencti-live-integration",
        page_size=1,
        timeout_seconds=30.0,
        max_retries=0,
        live_serving_enabled=False,
    )
    transport = create_live_transport(config)
    for kind in ("attack_pattern", "vulnerability", "report", "relationship"):
        page = transport.list_page(kind, filters=None, first=1, after=None)
        assert isinstance(page["entities"], list)
        assert isinstance(page["pagination"], dict)
        assert len(page["entities"]) <= 1
