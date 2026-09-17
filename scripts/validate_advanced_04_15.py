from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
P14_HANDOFF = "65701c1885ead1901e0f84c95227a1ced25190e2"
P14_TESTS = (
    "tests/unit/retrieval/test_context_packer.py",
    "tests/unit/retrieval/test_citations.py",
    "tests/e2e/test_evidence_egress.py",
)
P15_TESTS = (
    "tests/unit/api/test_advanced_identity.py",
    "tests/unit/evidence/test_corpus_access.py",
)


def run(args: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def main() -> int:
    if sys.version_info[:2] != (3, 11):
        raise SystemExit(
            "Prompt 04-15 chained validation requires Python 3.11; "
            f"observed {sys.version.split()[0]}"
        )

    run(["git", "merge-base", "--is-ancestor", P14_HANDOFF, "HEAD"])
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ADVANCED_RAG_")
    }
    env["PYTHONPATH"] = str(ROOT)

    print("\n=== Existing unresolved Prompt 04-13 correctness chain ===")
    run([sys.executable, "scripts/validate_advanced_04_13.py"], env=env)

    print("\n=== Prompt 14 packing/citation correctness gate ===")
    run([sys.executable, "-m", "pytest", *P14_TESTS, "-q"], env=env)

    print("\n=== Prompt 15 trusted identity/corpus access gate ===")
    run([sys.executable, "-m", "pytest", *P15_TESTS, "-q"], env=env)

    print("\n=== Prompt 15 import safety ===")
    run([
        sys.executable,
        "-c",
        "import packages.evidence.access; import rag.api.advanced_dependencies",
    ], env=env)

    print("\n=== Final compile/whitespace gates ===")
    run([
        sys.executable,
        "-m",
        "compileall",
        "-q",
        "packages",
        "benchmark",
        "rag",
        "tests",
        "scripts",
    ], env=env)
    run(["git", "diff", "--check"])

    print("\n=== Final full repository collection at Prompt 15 head ===")
    run([sys.executable, "-m", "pytest", "--collect-only", "-q"], env=env)

    run(["git", "status", "--short", "--branch"])
    run(["git", "rev-parse", "HEAD"])
    print(
        "VALIDATION_ADVANCED_04_15_CORRECTNESS_PASSED_WITH_"
        "INHERITED_REPORTED_SERVICE_SKIPS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
