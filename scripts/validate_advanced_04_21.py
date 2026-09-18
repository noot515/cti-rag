"""Strict Python 3.11 validation chain through Advanced RAG Prompt 21."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
P20_HEAD = "71c4cc0d88101e70b01592d4c4119834ba9f019a"


def run(label: str, command: list[str], *, env: dict[str, str]) -> None:
    print(f"\n=== {label} ===", flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {completed.returncode}")


def main() -> int:
    if sys.version_info[:2] != (3, 11):
        raise SystemExit(
            f"Prompt 04-21 validation requires Python 3.11; observed {sys.version.split()[0]}"
        )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["ADVANCED_RAG_STATE_DIR"] = "saves/validation/opencti-reconcile"

    run(
        "Verify Prompt 20 predecessor ancestry",
        ["git", "merge-base", "--is-ancestor", P20_HEAD, "HEAD"],
        env=env,
    )
    run(
        "Prompts 04-20 chained correctness gates",
        [sys.executable, "scripts/validate_advanced_04_20.py"],
        env=env,
    )
    run(
        "Prompt 21 visibility/revocation tests",
        [
            sys.executable, "-m", "pytest",
            "tests/unit/opencti/test_reconciliation.py",
            "tests/e2e/test_revocation_egress.py", "-q",
        ],
        env=env,
    )
    run(
        "Prompt 21 offline reconcile",
        [
            sys.executable, "-m", "packages.integrations.opencti.cli",
            "sync", "--config", "benchmark/advanced/configs/opencti.yaml",
            "--once", "--reconcile",
        ],
        env=env,
    )
    run(
        "Compile Prompt 21 surfaces",
        [
            sys.executable, "-m", "compileall", "-q",
            "packages/integrations/opencti", "packages/evidence",
            "packages/retrieval", "tests/unit/opencti", "tests/e2e",
        ],
        env=env,
    )
    run("Whitespace validation", ["git", "diff", "--check"], env=env)
    run(
        "Final repository pytest collection",
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        env=env,
    )
    run("Final git status", ["git", "status", "--short", "--branch"], env=env)
    run("Final HEAD", ["git", "rev-parse", "HEAD"], env=env)
    print("\nPROMPT_04_21_VALIDATION_PASSED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
