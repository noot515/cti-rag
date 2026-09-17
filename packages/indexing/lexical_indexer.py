"""Trusted exact and lexical projection writers for Prompt 07 publication."""
from __future__ import annotations

from pathlib import Path

from packages.evidence.ids import canonical_hash
from packages.retrieval.exact import ExactIndex, ExactIndexError
from packages.retrieval.lexical import LexicalIndex, LexicalIndexError
from .chunker import DeterministicTokenizer
from .manifests import GenerationManifest, ProjectionReceipt


class _WriterBase:
    backend: str

    def __init__(self, store, root: Path | str) -> None:
        self.store = store
        self.root = Path(root)

    def _spec(self, manifest: GenerationManifest):
        spec = next((item for item in manifest.enabled_projections if item.backend == self.backend), None)
        if spec is None:
            raise RuntimeError(f"manifest does not enable {self.backend} projection")
        if spec.fingerprint != self.fingerprint:
            raise RuntimeError(
                f"{self.backend} projection fingerprint mismatch: manifest={spec.fingerprint} writer={self.fingerprint}"
            )
        return spec

    def _receipt(self, manifest: GenerationManifest, artifact_sha256: str, sentinel: str) -> ProjectionReceipt:
        self._spec(manifest)
        return ProjectionReceipt(
            generation_id=manifest.generation_id,
            domain=manifest.domain,
            scope_id=manifest.scope_id,
            corpus_id=manifest.corpus_id,
            backend=self.backend,
            manifest_sha256=manifest.manifest_sha256,
            membership_sha256=manifest.membership_sha256,
            member_count=len(manifest.membership),
            fingerprint=self.fingerprint,
            artifact_sha256=artifact_sha256,
            visibility_verified=True,
            sentinel=sentinel,
        )


class ExactProjectionWriter(_WriterBase):
    backend = "exact"
    fingerprint = canonical_hash(["exact-projection-v1", "external-source-stix-identities", "json"])

    def build(self, manifest: GenerationManifest) -> ProjectionReceipt:
        self._spec(manifest)
        index = ExactIndex.build(self.store, root=self.root, manifest=manifest)
        return self._receipt(
            manifest,
            index.artifact_sha256,
            f"exact:{len(index.entries)}:{index.artifact_sha256[:16]}",
        )

    def verify(self, manifest: GenerationManifest, receipt: ProjectionReceipt) -> bool:
        try:
            self._spec(manifest)
            path = ExactIndex.path_for(
                self.root,
                domain=manifest.domain,
                scope_id=manifest.scope_id,
                generation_id=manifest.generation_id,
            )
            index = ExactIndex.open(self.store, path=path)
        except (ExactIndexError, OSError, RuntimeError):
            return False
        return (
            receipt.backend == self.backend
            and receipt.generation_id == manifest.generation_id
            and receipt.manifest_sha256 == manifest.manifest_sha256
            and receipt.membership_sha256 == manifest.membership_sha256
            and receipt.member_count == len(manifest.membership)
            and receipt.fingerprint == self.fingerprint
            and receipt.artifact_sha256 == index.artifact_sha256
            and receipt.sentinel == f"exact:{len(index.entries)}:{index.artifact_sha256[:16]}"
            and receipt.visibility_verified
        )


class LexicalProjectionWriter(_WriterBase):
    backend = "lexical"

    def __init__(
        self,
        store,
        root: Path | str,
        *,
        tokenizer: DeterministicTokenizer | None = None,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        super().__init__(store, root)
        self.tokenizer = tokenizer or DeterministicTokenizer()
        self.k1 = k1
        self.b = b
        self.fingerprint = canonical_hash(
            ["lexical-projection-v1", self.tokenizer.fingerprint, self.k1, self.b, "persistent-json-bm25"]
        )

    def build(self, manifest: GenerationManifest) -> ProjectionReceipt:
        self._spec(manifest)
        index = LexicalIndex.build(
            self.store,
            root=self.root,
            manifest=manifest,
            tokenizer=self.tokenizer,
            k1=self.k1,
            b=self.b,
        )
        return self._receipt(
            manifest,
            index.artifact_sha256,
            f"lexical:{len(index.docs)}:{index.artifact_sha256[:16]}",
        )

    def verify(self, manifest: GenerationManifest, receipt: ProjectionReceipt) -> bool:
        try:
            self._spec(manifest)
            path = LexicalIndex.path_for(
                self.root,
                domain=manifest.domain,
                scope_id=manifest.scope_id,
                generation_id=manifest.generation_id,
            )
            index = LexicalIndex.open(self.store, path=path, tokenizer=self.tokenizer)
        except (LexicalIndexError, OSError, RuntimeError):
            return False
        return (
            receipt.backend == self.backend
            and receipt.generation_id == manifest.generation_id
            and receipt.manifest_sha256 == manifest.manifest_sha256
            and receipt.membership_sha256 == manifest.membership_sha256
            and receipt.member_count == len(manifest.membership)
            and receipt.fingerprint == self.fingerprint
            and receipt.artifact_sha256 == index.artifact_sha256
            and receipt.sentinel == f"lexical:{len(index.docs)}:{index.artifact_sha256[:16]}"
            and receipt.visibility_verified
        )


__all__ = ["ExactProjectionWriter", "LexicalProjectionWriter"]
