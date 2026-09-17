"""Deterministic grouped dev/test split manifests with leakage checks."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import random
from typing import Iterable, Mapping


@dataclass(frozen=True)
class QueryGrouping:
    query_id: str
    object_cluster: str
    near_duplicate_family: str


@dataclass(frozen=True)
class SplitManifest:
    schema_version: str
    seed: int
    dev_fraction: float
    dev_query_ids: tuple[str, ...]
    test_query_ids: tuple[str, ...]
    grouping_sha256: str
    split_sha256: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256(encoded).hexdigest()


def grouped_split(
    groupings: Iterable[QueryGrouping],
    *,
    seed: int = 20260917,
    dev_fraction: float = 0.5,
) -> SplitManifest:
    rows = tuple(sorted(groupings, key=lambda item: item.query_id))
    if not rows:
        raise ValueError("cannot split an empty query set")
    if not (0.0 < dev_fraction < 1.0):
        raise ValueError("dev_fraction must be between 0 and 1")
    if len({row.query_id for row in rows}) != len(rows):
        raise ValueError("query IDs must be unique")

    # Union queries that share either an object/report cluster or a near-duplicate
    # family, so transitive overlap cannot leak across dev/test.
    parent = {row.query_id: row.query_id for row in rows}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_cluster: dict[str, list[str]] = {}
    by_family: dict[str, list[str]] = {}
    for row in rows:
        by_cluster.setdefault(row.object_cluster, []).append(row.query_id)
        by_family.setdefault(row.near_duplicate_family, []).append(row.query_id)
    for groups in (by_cluster, by_family):
        for ids in groups.values():
            for other in ids[1:]:
                union(ids[0], other)

    components: dict[str, list[str]] = {}
    for row in rows:
        components.setdefault(find(row.query_id), []).append(row.query_id)
    blocks = [tuple(sorted(ids)) for ids in components.values()]
    blocks.sort()
    rng = random.Random(seed)
    rng.shuffle(blocks)

    target = max(1, round(len(rows) * dev_fraction))
    dev: list[str] = []
    test: list[str] = []
    for block in blocks:
        if len(dev) < target and (len(dev) + len(block) <= target or not dev):
            dev.extend(block)
        else:
            test.extend(block)
    if not test and len(blocks) > 1:
        moved = blocks[-1]
        dev = [item for item in dev if item not in moved]
        test.extend(moved)
    if not dev or not test:
        raise ValueError("group constraints do not permit a nonempty dev/test split")

    grouping_payload = [asdict(row) for row in rows]
    split_payload = {
        "seed": seed,
        "dev_fraction": dev_fraction,
        "dev": sorted(dev),
        "test": sorted(test),
    }
    manifest = SplitManifest(
        schema_version="advanced-eval-split-v1",
        seed=seed,
        dev_fraction=dev_fraction,
        dev_query_ids=tuple(sorted(dev)),
        test_query_ids=tuple(sorted(test)),
        grouping_sha256=_canonical_hash(grouping_payload),
        split_sha256=_canonical_hash(split_payload),
    )
    assert_no_group_leakage(manifest, rows)
    return manifest


def assert_no_group_leakage(manifest: SplitManifest, groupings: Iterable[QueryGrouping]) -> None:
    by_id = {row.query_id: row for row in groupings}
    dev = set(manifest.dev_query_ids)
    test = set(manifest.test_query_ids)
    if dev & test:
        raise ValueError("query appears in both dev and test")
    for attribute in ("object_cluster", "near_duplicate_family"):
        dev_values = {getattr(by_id[item], attribute) for item in dev}
        test_values = {getattr(by_id[item], attribute) for item in test}
        overlap = dev_values & test_values
        if overlap:
            raise ValueError(f"{attribute} leakage across dev/test: {sorted(overlap)}")


__all__ = ["QueryGrouping", "SplitManifest", "assert_no_group_leakage", "grouped_split"]
