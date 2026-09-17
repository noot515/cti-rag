from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
P06_PREDECESSOR = "fb9a816ac083741fcce245c4e0b02fbd001e7c6e"
TESTS = (
    "tests/unit/indexing/test_publication.py",
    "tests/unit/indexing/test_publication_recovery.py",
    "tests/unit/indexing/test_chunker.py",
    "tests/unit/retrieval/test_exact.py",
    "tests/unit/retrieval/test_lexical.py",
    "tests/e2e/test_fixture_ingestion.py",
)


def run(args: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def main() -> int:
    if sys.version_info[:2] != (3, 11):
        raise SystemExit(
            f"Prompt 06/07 validation requires Python 3.11; observed {sys.version.split()[0]}"
        )

    run(["git", "merge-base", "--is-ancestor", P06_PREDECESSOR, "HEAD"])

    clean_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ADVANCED_RAG_")
    }
    clean_env["PYTHONPATH"] = str(ROOT)

    with tempfile.TemporaryDirectory(prefix="cti-rag-p06-p07-") as temp_dir:
        temp = Path(temp_dir)
        fixture_config = yaml.safe_load(
            (ROOT / "benchmark" / "advanced" / "configs" / "fixture.yaml").read_text(encoding="utf-8")
        )
        fixture_config["state_dir"] = str(temp / "fixture-state")
        config_path = temp / "fixture.yaml"
        config_path.write_text(
            yaml.safe_dump(fixture_config, sort_keys=False), encoding="utf-8"
        )

        run([sys.executable, "-m", "pytest", *TESTS, "-q"], env=clean_env)
        run(
            [
                sys.executable,
                "-m",
                "packages.indexing.cli",
                "ingest",
                "--config",
                str(config_path),
                "--manifest",
                "tests/fixtures/cti/corpus.manifest.json",
            ],
            env=clean_env,
        )
        run(
            [sys.executable, "-m", "compileall", "-q", "packages", "benchmark", "tests"],
            env=clean_env,
        )
        run(["git", "diff", "--check"])

    run(["git", "status", "--short", "--branch"])
    run(["git", "rev-parse", "HEAD"])
    print("VALIDATION_P06_P07_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
