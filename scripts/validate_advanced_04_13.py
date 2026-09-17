from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
P11_HANDOFF = "86593709fff8bab1b7b0153b1bad32f86ed3b651"
P12_HANDOFF = "358be5665a6d124bad5c5f01c794fe898ff30afb"
P12_P13_TESTS = (
    "tests/unit/retrieval/test_fusion.py",
    "tests/unit/retrieval/test_orchestrator.py",
    "tests/e2e/test_advanced_retrieval.py",
    "tests/unit/retrieval/test_reranker_contract.py",
    "tests/unit/retrieval/test_reranker_egress.py",
)


def run(args: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def main() -> int:
    if sys.version_info[:2] != (3, 11):
        raise SystemExit(
            f"Prompt 04-13 chained validation requires Python 3.11; observed {sys.version.split()[0]}"
        )

    run(["git", "merge-base", "--is-ancestor", P11_HANDOFF, "HEAD"])
    run(["git", "merge-base", "--is-ancestor", P12_HANDOFF, "HEAD"])

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ADVANCED_RAG_")
    }
    env["PYTHONPATH"] = str(ROOT)

    print("\n=== Chained unresolved Prompt 04-11 Python 3.11 validation ===")
    run([sys.executable, "scripts/validate_advanced_04_11.py"], env=env)

    print("\n=== Prompt 12/13 fusion, orchestration and final-reranker gate ===")
    run([sys.executable, "-m", "pytest", *P12_P13_TESTS, "-q"], env=env)

    print("\n=== Final Prompt 13 compile and whitespace gates ===")
    run(
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "packages",
            "benchmark",
            "tests",
            "scripts",
        ],
        env=env,
    )
    run(["git", "diff", "--check"])

    print("\n=== Final full repository collection gate at Prompt 13 head ===")
    run([sys.executable, "-m", "pytest", "--collect-only", "-q"], env=env)

    run(["git", "status", "--short", "--branch"])
    run(["git", "rev-parse", "HEAD"])
    print("VALIDATION_ADVANCED_04_13_CORRECTNESS_PASSED_WITH_PREDECESSOR_SERVICE_REPORTING")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
