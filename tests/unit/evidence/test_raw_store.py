from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path

import pytest

from packages.evidence.raw_store import RawHashConflict, RawHashMismatch, RawPayloadStore


def test_atomic_content_addressed_round_trip_and_reuse(tmp_path: Path):
    store = RawPayloadStore(tmp_path / "raw")
    data = b'{"synthetic":true}\n'
    digest = sha256(data).hexdigest()
    assert store.put(data, expected_sha256=digest) == digest
    assert store.read(digest) == data
    assert store.put(data, expected_sha256=digest) == digest
    assert not list((tmp_path / "raw").rglob("*.tmp"))


def test_expected_hash_mismatch_is_rejected_before_publication(tmp_path: Path):
    store = RawPayloadStore(tmp_path / "raw")
    with pytest.raises(RawHashMismatch):
        store.put(b"wrong", expected_sha256="a" * 64)
    assert not [path for path in (tmp_path / "raw").rglob("*") if path.is_file()]


def test_existing_digest_bytes_are_verified(tmp_path: Path):
    store = RawPayloadStore(tmp_path / "raw")
    data = b"expected"
    digest = sha256(data).hexdigest()
    target = store.path_for(digest)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"corrupt")
    with pytest.raises(RawHashConflict):
        store.put(data, expected_sha256=digest)
    with pytest.raises(RawHashConflict):
        store.read(digest)


def test_posix_permissions_are_restrictive(tmp_path: Path):
    store = RawPayloadStore(tmp_path / "raw")
    digest = store.put(b"x")
    if os.name != "nt":
        assert (store.root.stat().st_mode & 0o777) == 0o700
        assert (store.path_for(digest).stat().st_mode & 0o777) == 0o600
