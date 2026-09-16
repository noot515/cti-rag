from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.domains.cti import CtiDomainAdapter

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "cti" / "public_fixture.json"


def test_bundled_fixture_requires_explicit_synthetic_marker():
    manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
    manifest["synthetic"] = False
    with pytest.raises(ValueError, match="synthetic=true"):
        CtiDomainAdapter().normalize(manifest)


def test_unreviewed_relation_is_rejected():
    manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
    manifest["relations"][0]["normalized_relation"] = "causes_everything"
    with pytest.raises(ValueError, match="unreviewed CTI relation"):
        CtiDomainAdapter().normalize(manifest)
