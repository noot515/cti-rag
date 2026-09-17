"""Trusted local administration CLI for advanced evidence access state."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from pydantic import Field

from packages.evidence.access import CorpusAccessStore, CorpusRegistrationManifest
from packages.evidence.policy import TrustedPrincipal
from packages.evidence.schema import EvidenceModel


class CliAdministrator(EvidenceModel):
    principal_namespace: str = Field(min_length=1)
    principal_id: str = Field(min_length=1)
    capabilities: frozenset[str]


class EvidenceCliConfig(EvidenceModel):
    access_store_path: str = Field(min_length=1)
    administrator: CliAdministrator


def _yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a mapping")
    return payload


def register_corpus(config_path: Path, grant_path: Path) -> None:
    config = EvidenceCliConfig.model_validate(_yaml(config_path))
    manifest = CorpusRegistrationManifest.model_validate(_yaml(grant_path))
    actor = TrustedPrincipal(
        principal_id=config.administrator.principal_id,
        principal_namespace=config.administrator.principal_namespace,
        source="trusted_local_cli",
        capabilities=config.administrator.capabilities,
    )
    with CorpusAccessStore(config.access_store_path) as store:
        store.register_corpus(manifest, actor=actor)
    # Print only the public corpus key; no principal IDs, secrets or grant contents.
    print(f"registered corpus {manifest.corpus_key}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m packages.evidence.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register-corpus")
    register.add_argument("--config", required=True, type=Path)
    register.add_argument("--grant-file", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "register-corpus":
        register_corpus(args.config, args.grant_file)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
