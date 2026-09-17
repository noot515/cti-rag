from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
P09_HANDOFF = "b76830493d41bb0b6931187ffbd8a406299aedb3"
P10_HANDOFF = "1667ddb1d155412a46fa86c3c17acef30d76da54"

P04_P05_TESTS = (
    "tests/unit/cti",
    "tests/unit/benchmark/test_data_boundary.py",
    "tests/unit/evidence/test_store.py",
    "tests/unit/evidence/test_raw_store.py",
)
P10_P11_TESTS = (
    "tests/unit/indexing/test_graph_projection.py",
    "tests/unit/retrieval/test_graph_paths.py",
    "tests/unit/retrieval/test_planner.py",
    "tests/unit/retrieval/test_target_projection.py",
)


def run(args: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def main() -> int:
    if sys.version_info[:2] != (3, 11):
        raise SystemExit(
            f"Prompt 04-11 chained validation requires Python 3.11; observed {sys.version.split()[0]}"
        )

    run(["git", "merge-base", "--is-ancestor", P09_HANDOFF, "HEAD"])
    run(["git", "merge-base", "--is-ancestor", P10_HANDOFF, "HEAD"])

    env = {key: value for key, value in os.environ.items() if not key.startswith("ADVANCED_RAG_")}
    env["PYTHONPATH"] = str(ROOT)

    print("\n=== Previously unresolved Prompt 04/05 Python 3.11 correctness gate ===")
    run([sys.executable, "-m", "pytest", *P04_P05_TESTS, "-q"], env=env)

    print("\n=== Previously unresolved Prompt 06/07 Python 3.11 chain ===")
    run([sys.executable, "scripts/validate_advanced_06_07.py"], env=env)

    print("\n=== Previously unresolved Prompt 08/09 Python 3.11 chain ===")
    run([sys.executable, "scripts/validate_advanced_08_09.py"], env=env)

    print("\n=== Prompt 10/11 correctness gate ===")
    run([sys.executable, "-m", "pytest", *P10_P11_TESTS, "-q"], env=env)

    print("\n=== Compile and whitespace gates ===")
    run([sys.executable, "-m", "compileall", "-q", "packages", "benchmark", "tests", "scripts"], env=env)
    run(["git", "diff", "--check"])

    print("\n=== Full repository collection gate ===")
    run([sys.executable, "-m", "pytest", "--collect-only", "-q"], env=env)

    docker = shutil.which("docker")
    if docker is None:
        print("SERVICE_GATES_NOT_RUN: docker command unavailable")
    else:
        compose_env = dict(env)
        compose_env.setdefault("ADVANCED_MINIO_ACCESS_KEY", "validation-only-access-key")
        compose_env.setdefault("ADVANCED_MINIO_SECRET_KEY", "validation-only-secret-key")
        compose_env.setdefault("ADVANCED_NEO4J_USERNAME", "validation-only-neo4j")
        compose_env.setdefault("ADVANCED_NEO4J_PASSWORD", "validation-only-password")
        print("\n=== Advanced Compose syntax/isolation configuration gate ===")
        run([docker, "compose", "-f", "deploy/advanced-services.compose.yml", "config", "--quiet"], env=compose_env)

        if os.getenv("RUN_ADVANCED_NEO4J_INTEGRATION") == "1":
            print("\n=== Real isolated Neo4j integration gate ===")
            run([docker, "compose", "-f", "deploy/advanced-services.compose.yml", "up", "-d", "advanced-neo4j"], env=compose_env)
            run([
                sys.executable,
                "-m",
                "pytest",
                "tests/integration/test_advanced_neo4j.py",
                "-m",
                "integration",
                "-q",
            ], env=env)
        else:
            print(
                "REAL_NEO4J_GATE_NOT_RUN: set RUN_ADVANCED_NEO4J_INTEGRATION=1 "
                "and supply advanced/legacy integration credentials to run it"
            )

    run(["git", "status", "--short", "--branch"])
    run(["git", "rev-parse", "HEAD"])
    print("VALIDATION_ADVANCED_04_11_CORRECTNESS_PASSED_WITH_REPORTED_SERVICE_SKIPS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
