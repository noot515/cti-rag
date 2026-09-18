"""Strict Python 3.11 validation chain through Advanced RAG Prompt 19."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
P18_HEAD = "d61d475735a9f1cc931fe91f709732aa2c7dd5e8"


def run(label: str, command: list[str], *, env: dict[str, str]) -> None:
    print(f"\n=== {label} ===", flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {completed.returncode}")


def not_run(label: str, reason: str) -> None:
    print(f"\n=== {label} ===", flush=True)
    print(f"NOT_RUN: {reason}", flush=True)


def main() -> int:
    if sys.version_info[:2] != (3, 11):
        raise SystemExit(
            f"Prompt 04-19 validation requires Python 3.11; observed {sys.version.split()[0]}"
        )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["ADVANCED_RAG_STATE_DIR"] = "saves/validation/opencti-fixture"

    run(
        "Verify Prompt 18 predecessor ancestry",
        ["git", "merge-base", "--is-ancestor", P18_HEAD, "HEAD"],
        env=env,
    )
    run(
        "Prompts 04-18 chained correctness gates",
        [sys.executable, "scripts/validate_advanced_04_18.py"],
        env=env,
    )
    run(
        "Prompt 19 OpenCTI unit contracts",
        [sys.executable, "-m", "pytest", "tests/unit/opencti", "-q"],
        env=env,
    )
    run(
        "Prompt 19 sanitized fixture one-shot sync",
        [
            sys.executable, "-m", "packages.integrations.opencti.cli",
            "sync", "--config", "benchmark/advanced/configs/opencti.yaml", "--once",
        ],
        env=env,
    )

    if env.get("OPENCTI_TEST_LIVE") == "1":
        if not env.get("OPENCTI_API_URL") or not env.get("OPENCTI_API_TOKEN"):
            raise SystemExit(
                "OPENCTI_TEST_LIVE=1 requires OPENCTI_API_URL and OPENCTI_API_TOKEN"
            )
        run(
            "Prompt 19 live read-only OpenCTI gate",
            [
                sys.executable, "-m", "pytest",
                "tests/integration/test_opencti_read.py",
                "-m", "opencti", "-q",
            ],
            env=env,
        )
    else:
        not_run(
            "Prompt 19 live read-only OpenCTI gate",
            "OPENCTI_TEST_LIVE is not 1; no deployed read-only OpenCTI environment was authorized",
        )

    run(
        "Compile Prompt 19 and predecessor Python surfaces",
        [
            sys.executable, "-m", "compileall", "-q",
            "benchmark/advanced", "benchmark/cticonnect",
            "packages/evidence", "packages/indexing", "packages/integrations",
            "tests/unit/opencti", "tests/integration",
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
    print("\nPROMPT_04_19_VALIDATION_PASSED_WITH_OPTIONAL_GATES_REPORTED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
