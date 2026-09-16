from __future__ import annotations

import pytest

from packages.domains.cti.identifiers import normalize_identifier, normalize_observable, parse_cti_identifiers


def test_valid_and_malformed_catalog_identifiers():
    found = parse_cti_identifiers("CVE-2026-999999 CWE-79 CAPEC-66 T1059.001 T1059")
    assert [(item.namespace, item.value) for item in found] == [
        ("cve", "CVE-2026-999999"),
        ("cwe", "CWE-79"),
        ("capec", "CAPEC-66"),
        ("attack", "T1059.001"),
        ("attack", "T1059"),
    ]
    with pytest.raises(ValueError):
        normalize_identifier("cve", "CVE-TEST-0001")
    with pytest.raises(ValueError):
        normalize_identifier("attack", "T1059.01")


def test_observables_are_type_checked_and_canonicalized():
    assert normalize_observable("ipv4", "192.0.2.1").value == "192.0.2.1"
    assert normalize_observable("ipv6", "2001:0db8::1").value == "2001:db8::1"
    assert normalize_observable("sha256", "A" * 64).value == "a" * 64
    assert normalize_observable("domain", "Example.COM.").value == "example.com"
    with pytest.raises(ValueError):
        normalize_observable("ipv4", "999.1.1.1")
    with pytest.raises(ValueError):
        normalize_observable("sha256", "aa")
    with pytest.raises(ValueError):
        normalize_observable("domain", "https://example.com")


def test_boundaries_do_not_parse_embedded_identifiers():
    values = [item.value for item in parse_cti_identifiers("XCVE-2026-999999Z fooT1059.001bar CVE-2026-999999")]
    assert values == ["CVE-2026-999999"]
