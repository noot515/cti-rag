"""Strict Python 3.11 validation chain through Advanced RAG Prompt 18."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
P17_HEAD = "1a39055dba7938f96b2462d1392e0f617242597b"


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
            f"Prompt 04-18 validation requires Python 3.11; observed {sys.version.split()[0]}"
        )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)

    run(
        "Verify Prompt 17 predecessor ancestry",
        ["git", "merge-base", "--is-ancestor", P17_HEAD, "HEAD"],
        env=env,
    )
    run(
        "Prompts 04-17 chained correctness gates",
        [sys.executable, "scripts/validate_advanced_04_17.py"],
        env=env,
    )
    run(
        "Prompt 18 CTIConnect unit contracts",
        [sys.executable, "-m", "pytest", "tests/unit/benchmark/test_cticonnect_adapter.py", "-q"],
        env=env,
    )

    external = env.get("CTICONNECT_PATH")
    if external:
        run(
            "Prompt 18 pinned external corpus integration",
            [sys.executable, "-m", "pytest", "tests/integration/test_cticonnect_corpus.py", "-m", "integration", "-q"],
            env=env,
        )
        run(
            "Prompt 18 CTIConnect retrieval experiment",
            [
                sys.executable, "-m", "benchmark.advanced.run_retrieval_eval",
                "--config", "benchmark/advanced/configs/cticonnect.yaml",
                "--output", "saves/eval/cticonnect",
            ],
            env=env,
        )
    else:
        reason = (
            "CTICONNECT_PATH is unset; clone peng-gao-lab/CTIConnect at "
            "554797d69a51147f1f98fad7198cb2d2b183d0e9 outside this repository"
        )
        not_run("Prompt 18 pinned external corpus integration", reason)
        not_run("Prompt 18 CTIConnect retrieval experiment", reason)

    run(
        "Compile Prompt 18 and predecessor Python surfaces",
        [
            sys.executable, "-m", "compileall", "-q",
            "benchmark/advanced", "benchmark/cticonnect", "packages/evidence",
            "packages/retrieval", "tests/unit/benchmark", "tests/integration",
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
    print("\nPROMPT_04_18_VALIDATION_PASSED_WITH_OPTIONAL_GATES_REPORTED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
