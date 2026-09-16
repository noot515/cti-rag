"""Content-addressed raw-payload storage with atomic publication."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import tempfile

from .validation import require_sha256


class RawStoreError(IOError):
    pass


class RawHashMismatch(RawStoreError):
    pass


class RawHashConflict(RawStoreError):
    pass


def _chmod_private(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class RawPayloadStore:
    """Private content-addressed bytes published before catalog references."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        _chmod_private(self.root, 0o700)

    def path_for(self, digest: str) -> Path:
        require_sha256(digest, field_name="raw_payload_sha256")
        return self.root / digest[:2] / digest[2:4] / digest

    def exists(self, digest: str) -> bool:
        return self.path_for(digest).is_file()

    def put(self, data: bytes, *, expected_sha256: str | None = None) -> str:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("raw payload must be bytes")
        raw = bytes(data)
        digest = sha256(raw).hexdigest()
        if expected_sha256 is not None:
            require_sha256(expected_sha256, field_name="expected_sha256")
            if digest != expected_sha256:
                raise RawHashMismatch(
                    f"raw payload hash mismatch: expected {expected_sha256}, observed {digest}"
                )

        target = self.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        _chmod_private(target.parent.parent, 0o700)
        _chmod_private(target.parent, 0o700)

        if target.exists():
            observed = sha256(target.read_bytes()).hexdigest()
            if observed != digest:
                raise RawHashConflict(f"existing raw payload bytes conflict for digest {digest}")
            return digest

        fd, tmp_name = tempfile.mkstemp(prefix=f".{digest}.", suffix=".tmp", dir=target.parent)
        tmp = Path(tmp_name)
        try:
            _chmod_private(tmp, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())

            if target.exists():
                observed = sha256(target.read_bytes()).hexdigest()
                if observed != digest:
                    raise RawHashConflict(f"existing raw payload bytes conflict for digest {digest}")
                tmp.unlink(missing_ok=True)
                return digest

            os.replace(tmp, target)
            _chmod_private(target, 0o600)
            _fsync_dir(target.parent)
            observed = sha256(target.read_bytes()).hexdigest()
            if observed != digest:
                raise RawHashConflict(f"published raw payload bytes conflict for digest {digest}")
            return digest
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def read(self, digest: str) -> bytes:
        target = self.path_for(digest)
        try:
            raw = target.read_bytes()
        except FileNotFoundError as exc:
            raise RawStoreError(f"raw payload not found: {digest}") from exc
        observed = sha256(raw).hexdigest()
        if observed != digest:
            raise RawHashConflict(f"stored raw payload bytes conflict for digest {digest}")
        return raw
