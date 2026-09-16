"""Deterministic CTI identifier and observable normalization."""

from __future__ import annotations

import ipaddress
import re

from packages.evidence.schema import ExternalIdentifier

_IDENTIFIER_PATTERNS = (
    ("cve", re.compile(r"(?<![A-Z0-9-])CVE-\d{4}-\d{4,}(?![A-Z0-9-])", re.I), "CVE"),
    ("cwe", re.compile(r"(?<![A-Z0-9-])CWE-\d+(?![A-Z0-9-])", re.I), "CWE"),
    ("capec", re.compile(r"(?<![A-Z0-9-])CAPEC-\d+(?![A-Z0-9-])", re.I), "CAPEC"),
    ("attack", re.compile(r"(?<![A-Z0-9.])T\d{4}(?:\.\d{3})?(?![A-Z0-9.])", re.I), "ATT&CK"),
)
_HASH_LENGTHS = {"md5": 32, "sha1": 40, "sha256": 64}
_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_identifier(namespace: str, value: str) -> ExternalIdentifier:
    ns = namespace.strip().lower()
    val = value.strip().upper()
    if ns == "attack":
        taxonomy = "MITRE ATT&CK"
    elif ns in {"cve", "cwe", "capec"}:
        taxonomy = ns.upper()
    else:
        return normalize_observable(ns, value)
    for known, pattern, _ in _IDENTIFIER_PATTERNS:
        if known == ns and pattern.fullmatch(val):
            return ExternalIdentifier(namespace=ns, value=val, taxonomy=taxonomy, domain="cti")
    raise ValueError(f"invalid {ns} identifier: {value}")


def normalize_observable(namespace: str, value: str) -> ExternalIdentifier:
    if not isinstance(value, str):
        raise TypeError("observable value must be a string")
    ns = namespace.strip().lower()
    raw = value.strip()
    if ns in {"ipv4", "ipv6"}:
        address = ipaddress.ip_address(raw)
        if (ns == "ipv4" and address.version != 4) or (ns == "ipv6" and address.version != 6):
            raise ValueError(f"invalid {ns} value: {value}")
        return ExternalIdentifier(namespace=ns, value=str(address), taxonomy="IP", domain="cti")
    if ns in _HASH_LENGTHS:
        normalized = raw.lower()
        if len(normalized) != _HASH_LENGTHS[ns] or re.fullmatch(r"[0-9a-f]+", normalized) is None:
            raise ValueError(f"invalid {ns} hash: {value}")
        return ExternalIdentifier(namespace=ns, value=normalized, taxonomy="file-hash", domain="cti")
    if ns == "domain":
        if "://" in raw or "/" in raw or not raw:
            raise ValueError(f"invalid domain value: {value}")
        try:
            ascii_value = raw.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError(f"invalid domain value: {value}") from exc
        labels = ascii_value.split(".")
        if len(labels) < 2 or any(_DOMAIN_LABEL.fullmatch(label) is None for label in labels):
            raise ValueError(f"invalid domain value: {value}")
        try:
            ipaddress.ip_address(ascii_value)
        except ValueError:
            pass
        else:
            raise ValueError(f"invalid domain value: {value}")
        return ExternalIdentifier(namespace=ns, value=ascii_value, taxonomy="dns", domain="cti")
    raise ValueError(f"unsupported CTI identifier namespace: {namespace}")


def parse_cti_identifiers(text: str) -> list[ExternalIdentifier]:
    found: list[ExternalIdentifier] = []
    seen: set[tuple[str, str]] = set()
    for namespace, pattern, _ in _IDENTIFIER_PATTERNS:
        for match in pattern.finditer(text):
            identifier = normalize_identifier(namespace, match.group(0))
            key = (identifier.namespace, identifier.value)
            if key not in seen:
                found.append(identifier)
                seen.add(key)
    return found


def exact_identifier_key(identifier: ExternalIdentifier) -> str:
    return f"{identifier.namespace}:{identifier.value}"
