"""Manual NER endpoint smoke probe.

This file lives under tests/ for historical reasons, but it is not a pytest test.
Importing it must remain inert so repository collection and compile validation never
perform network I/O.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_URL = "http://localhost:8000/graph/extract-entities-from-file"


def _load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("payload JSON must contain an object at the top level")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual NER endpoint smoke probe")
    parser.add_argument(
        "--payload",
        required=True,
        type=Path,
        help="Path to the JSON request payload",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="NER endpoint URL",
    )
    parser.add_argument(
        "--timeout",
        default=30.0,
        type=float,
        help="HTTP timeout in seconds",
    )
    args = parser.parse_args(argv)

    import requests

    response = requests.post(
        args.url,
        json=_load_payload(args.payload),
        timeout=args.timeout,
    )
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
