"""CLI for one-shot, read-only OpenCTI capture and publication."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .sync import sync_once


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Advanced read-only OpenCTI capture")
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="capture a finite complete scan and publish it")
    sync.add_argument("--config", required=True, type=Path)
    sync.add_argument("--once", action="store_true", help="required finite one-shot mode")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "sync":
        raise AssertionError(args.command)
    if not args.once:
        raise SystemExit("Prompt 19 supports only explicit --once finite scans")
    report = sync_once(config_path=args.config)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
