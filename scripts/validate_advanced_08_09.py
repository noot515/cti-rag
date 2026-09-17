from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
P08_PREDECESSOR = "397f3ba49b94bc93a462b7e09c2f7d51f76bd4c5"
UNIT_TESTS = (
    "tests/unit/retrieval/test_embedding_provider.py",
    "tests/unit/retrieval/test_fixture_dense.py",
    "tests/unit/indexing/test_milvus_adapter.py",
)


def run(args: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def main() -> int:
    if sys.version_info[:2] != (3, 11):
        raise SystemExit(
            f"Prompt 08/09 validation requires Python 3.11; observed {sys.version.split()[0]}"
        )
    run(["git", "merge-base", "--is-ancestor", P08_PREDECESSOR, "HEAD"])
    env = {key: value for key, value in os.environ.items() if not key.startswith("ADVANCED_RAG_")}
    env["PYTHONPATH"] = str(ROOT)

    run([sys.executable, "-m", "pytest", *UNIT_TESTS, "-q"], env=env)
    run([sys.executable, "-m", "compileall", "-q", "packages", "benchmark", "tests"], env=env)
    run(["git", "diff", "--check"])

    docker = shutil.which("docker")
    if docker is None:
        print("SERVICE_GATE_NOT_RUN: docker command unavailable")
    else:
        compose_env = dict(env)
        compose_env.setdefault("ADVANCED_MINIO_ACCESS_KEY", "validation-only-access-key")
        compose_env.setdefault("ADVANCED_MINIO_SECRET_KEY", "validation-only-secret-key")
        # Prompt 10 added a second service with mandatory credentials. These values
        # are validation-only placeholders so the historical P08/P09 Compose parse
        # remains runnable without weakening the service's required-secret contract.
        compose_env.setdefault("ADVANCED_NEO4J_USERNAME", "validation-only-neo4j")
        compose_env.setdefault("ADVANCED_NEO4J_PASSWORD", "validation-only-password")
        run([docker, "compose", "-f", "deploy/advanced-services.compose.yml", "config", "--quiet"], env=compose_env)
        if os.getenv("RUN_ADVANCED_MILVUS_INTEGRATION") == "1":
            run([docker, "compose", "-f", "deploy/advanced-services.compose.yml", "up", "-d", "advanced-milvus"], env=compose_env)
            run([
                sys.executable, "-m", "pytest", "tests/integration/test_advanced_milvus.py", "-q", "-m", "integration"
            ], env=env)
        else:
            print("REAL_MILVUS_GATE_NOT_RUN: set RUN_ADVANCED_MILVUS_INTEGRATION=1 with integration URIs")

    run(["git", "status", "--short", "--branch"])
    run(["git", "rev-parse", "HEAD"])
    print("VALIDATION_P08_P09_OFFLINE_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
