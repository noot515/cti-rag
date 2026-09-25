#!/usr/bin/env python3
"""Run cumulative validation gates through a requested implementation phase."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

VALID_STATUSES = {"pass", "fail", "blocked", "not_run"}


def load_registry(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("schema_version") != "validation-registry/1":
        raise ValueError("unsupported validation registry schema")
    return data


def run_gate(gate, root: Path):
    if gate.get("status_override"):
        status = gate["status_override"]
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status_override {status!r}")
        return {**gate, "status": status, "returncode": None, "stdout": "", "stderr": gate.get("reason", "")}
    command = gate.get("command")
    if not command:
        return {**gate, "status": "blocked", "returncode": None, "stdout": "", "stderr": "missing command"}
    proc = subprocess.run(command, cwd=root, shell=True, text=True, capture_output=True)
    return {
        **gate,
        "status": "pass" if proc.returncode == 0 else "fail",
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--through-phase", type=int, required=True)
    parser.add_argument("--registry", default="validation/gates.json")
    parser.add_argument("--report")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    registry = load_registry(root / args.registry)
    selected = [g for g in registry["gates"] if int(g["phase"]) <= args.through_phase]
    results = [run_gate(g, root) for g in selected]
    ok = all((not g.get("required", True)) or g["status"] == "pass" for g in results)
    report = {"through_phase": args.through_phase, "status": "pass" if ok else "fail", "gates": results}
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.report:
        report_path = root / args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
