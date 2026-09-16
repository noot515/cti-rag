"""Deterministic CTI identifier parsing and normalization."""

from __future__ import annotations

import re

from packages.evidence.schema import ExternalIdentifier

_IDENTIFIER_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("cve", re.compile(r"(?<![A-Z0-9-])CVE-\d{4}-\d{4,}(?![A-Z0-9-])", re.IGNORECASE), "CVE"),
    ("cwe", re.compile(r"(?<![A-Z0-9-])CWE-\d+(?![A-Z0-9-])", re.IGNORECASE), "CWE"),
    ("capec", re.compile(r"(?<![A-Z0-9-])CAPEC-\d+(?![A-Z0-9-])", re.IGNORECASE), "CAPEC"),
    (
        "attack",
        re.compile(r"(?<![A-Z0-9.])T\d{4}(?:\.\d{3})?(?![A-Z0-9.])", re.IGNORECASE),
        "ATT&CK",
    ),
)


def normalize_identifier(namespace: str, value: str) -> ExternalIdentifier:
    normalized_namespace = namespace.strip().lower()
    normalized_value = value.strip().upper()
    taxonomy = None
    if normalized_namespace == "attack":
        taxonomy = "MITRE ATT&CK"
    elif normalized_namespace in {"cve", "cwe", "capec"}:
        taxonomy = normalized_namespace.upper()
    else:
        raise ValueError(f"unsupported CTI identifier namespace: {namespace}")

    for known_namespace, pattern, _ in _IDENTIFIER_PATTERNS:
        if known_namespace == normalized_namespace and pattern.fullmatch(normalized_value):
            return ExternalIdentifier(
                namespace=normalized_namespace,
                value=normalized_value,
                taxonomy=taxonomy,
                domain="cti",
            )
    raise ValueError(f"invalid {normalized_namespace} identifier: {value}")


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
