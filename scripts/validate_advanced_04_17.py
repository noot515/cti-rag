"""Strict Python 3.11 validation chain through Advanced RAG Prompts 04-17."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
P16_HEAD = "1b0e03fc3a54367cb0930318db6477a2667b8e02"


def run(label: str, command: list[str], *, env: dict[str, str] | None = None) -> None:
    print(f"\n=== {label} ===", flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {completed.returncode}")


def main() -> int:
    if sys.version_info[:2] != (3, 11):
        raise SystemExit(
            f"Prompt 04-17 validation requires Python 3.11; observed {sys.version.split()[0]}"
        )

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)

    run(
        "Verify Prompt 16 predecessor ancestry",
        ["git", "merge-base", "--is-ancestor", P16_HEAD, "HEAD"],
        env=env,
    )
    run(
        "Prompts 04-15 predecessor chain",
        [sys.executable, "scripts/validate_advanced_04_15.py"],
        env=env,
    )
    run(
        "Prompt 16 authenticated advanced API",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/api/test_advanced_route.py",
            "tests/e2e/test_advanced_api.py",
            "-q",
        ],
        env=env,
    )
    run(
        "Prompt 16 import safety",
        [sys.executable, "-m", "pytest", "tests/unit/evidence/test_imports.py", "-q"],
        env=env,
    )
    run(
        "Prompt 17 metrics, ablations, and report contracts",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/benchmark",
            "tests/e2e/test_eval_report.py",
            "-q",
        ],
        env=env,
    )
    run(
        "Prompt 17 offline retrieval report",
        [
            sys.executable,
            "-m",
            "benchmark.advanced.run_retrieval_eval",
            "--config",
            "benchmark/advanced/configs/fixture.yaml",
            "--output",
            "saves/eval/fixture",
        ],
        env=env,
    )
    run(
        "Prompt 17 offline answer report",
        [
            sys.executable,
            "-m",
            "benchmark.advanced.run_answer_eval",
            "--config",
            "benchmark/advanced/configs/fixture.yaml",
            "--output",
            "saves/eval/fixture-answers",
        ],
        env=env,
    )
    run(
        "Compile advanced modules and tests",
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "benchmark/advanced",
            "packages/evidence",
            "packages/retrieval",
            "rag/api",
            "tests/unit/benchmark",
            "tests/unit/api",
            "tests/e2e",
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
    print("\nPROMPT_04_17_VALIDATION_PASSED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
