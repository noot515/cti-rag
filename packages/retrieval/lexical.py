"""Persistent full-generation BM25 over validated immutable chunks."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from packages.evidence.ids import canonical_json
from packages.evidence.policy import ResolvedScope, require_authorized
from packages.evidence.schema import AuthorizedEvidenceView, EvidencePolicyMetadata, SnapshotRef
from packages.indexing.chunker import DeterministicTokenizer
from packages.indexing.manifests import GenerationManifest
from .candidate import BackendHit


class LexicalIndexError(RuntimeError):
    pass


def _safe_component(value: str) -> str:
    if value and all(ch.isalnum() or ch in "._-" for ch in value):
        return value
    return sha256(value.encode("utf-8")).hexdigest()


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


class LexicalIndex:
    schema_version = "lexical-index-v1"
    name = "lexical"

    def __init__(self, store: Any, path: Path, payload: dict[str, Any], tokenizer: DeterministicTokenizer) -> None:
        self.store = store
        self.path = path
        self.payload = payload
        self.tokenizer = tokenizer
        self.domain = str(payload["domain"])
        self.scope_id = str(payload["scope_id"])
        self.corpus_id = str(payload["corpus_id"])
        self.generation_id = str(payload["generation_id"])
        self.manifest_sha256 = str(payload["manifest_sha256"])
        self.membership_sha256 = str(payload["membership_sha256"])
        self.k1 = float(payload["k1"])
        self.b = float(payload["b"])
        self.docs = tuple(payload["documents"])
        self.df = {str(key): int(value) for key, value in payload["df"].items()}
        self.avgdl = float(payload["avgdl"])

    @classmethod
    def path_for(cls, root: Path | str, *, domain: str, scope_id: str, generation_id: str) -> Path:
        return Path(root) / _safe_component(domain) / _safe_component(scope_id) / _safe_component(generation_id) / "lexical.json"

    @classmethod
    def build(cls, store: Any, *, root: Path | str, manifest: GenerationManifest, tokenizer: DeterministicTokenizer | None = None, k1: float = 1.5, b: float = 0.75) -> "LexicalIndex":
        if k1 <= 0 or not (0.0 <= b <= 1.0):
            raise ValueError("BM25 requires k1 > 0 and 0 <= b <= 1")
        tokenizer = tokenizer or DeterministicTokenizer()
        generation = store.connection.execute(
            "SELECT manifest_sha256 FROM generation_manifests WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?",
            (manifest.domain, manifest.scope_id, manifest.corpus_id, manifest.generation_id),
        ).fetchone()
        if generation is None or generation["manifest_sha256"] != manifest.manifest_sha256:
            raise LexicalIndexError("generation manifest is missing or mismatched")
        rows = store.connection.execute(
            "SELECT c.chunk_uid,c.object_uid,c.object_revision_uid,c.payload_json FROM snapshot_membership sm JOIN chunks c "
            "ON c.domain=sm.domain AND c.scope_id=sm.scope_id AND c.chunk_uid=sm.evidence_uid "
            "WHERE sm.domain=? AND sm.scope_id=? AND sm.snapshot_id=? AND sm.evidence_kind='chunk' ORDER BY c.chunk_uid",
            (manifest.domain, manifest.scope_id, manifest.generation_id),
        ).fetchall()
        documents: list[dict[str, Any]] = []
        df: Counter[str] = Counter()
        total_len = 0
        for row in rows:
            chunk = json.loads(row["payload_json"])
            text = str(chunk["text"])
            observed_hash = sha256(text.encode("utf-8")).hexdigest()
            if observed_hash != chunk["content_hash"]:
                raise LexicalIndexError(f"chunk content hash mismatch: {row['chunk_uid']}")
            if chunk.get("tokenizer_fingerprint") != tokenizer.fingerprint:
                raise LexicalIndexError("chunk tokenizer fingerprint does not match lexical tokenizer")
            tokens = tokenizer.tokens(text)
            if int(chunk.get("token_count", -1)) != len(tokens):
                raise LexicalIndexError("chunk token count does not match validated tokenization")
            total_len += len(tokens)
            for term in set(tokens):
                df[term] += 1
            documents.append({"chunk_uid": row["chunk_uid"], "object_uid": row["object_uid"], "object_revision_uid": row["object_revision_uid"], "content_hash": observed_hash, "token_count": len(tokens), "tokens": list(tokens)})
        avgdl = total_len / len(documents) if documents else 0.0
        payload = {
            "schema_version": cls.schema_version,
            "domain": manifest.domain,
            "scope_id": manifest.scope_id,
            "corpus_id": manifest.corpus_id,
            "generation_id": manifest.generation_id,
            "manifest_sha256": manifest.manifest_sha256,
            "membership_sha256": manifest.membership_sha256,
            "tokenizer_fingerprint": tokenizer.fingerprint,
            "k1": k1,
            "b": b,
            "document_count": len(documents),
            "avgdl": avgdl,
            "df": dict(sorted(df.items())),
            "documents": documents,
        }
        path = cls.path_for(root, domain=manifest.domain, scope_id=manifest.scope_id, generation_id=manifest.generation_id)
        _atomic_bytes(path, canonical_json(payload).encode("utf-8"))
        return cls.open(store, path=path, tokenizer=tokenizer)

    @classmethod
    def open(cls, store: Any, *, path: Path | str, tokenizer: DeterministicTokenizer | None = None) -> "LexicalIndex":
        tokenizer = tokenizer or DeterministicTokenizer()
        path = Path(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LexicalIndexError("lexical index cannot be read") from exc
        if payload.get("schema_version") != cls.schema_version:
            raise LexicalIndexError("unsupported lexical index schema")
        if payload.get("tokenizer_fingerprint") != tokenizer.fingerprint:
            raise LexicalIndexError("tokenizer fingerprint mismatch")
        generation = store.connection.execute(
            "SELECT manifest_sha256,manifest_json FROM generation_manifests WHERE domain=? AND scope_id=? AND corpus_id=? AND generation_id=?",
            (payload.get("domain"), payload.get("scope_id"), payload.get("corpus_id"), payload.get("generation_id")),
        ).fetchone()
        if generation is None or generation["manifest_sha256"] != payload.get("manifest_sha256"):
            raise LexicalIndexError("generation manifest no longer matches lexical index")
        manifest = GenerationManifest.model_validate_json(generation["manifest_json"])
        if manifest.membership_sha256 != payload.get("membership_sha256"):
            raise LexicalIndexError("generation membership hash no longer matches lexical index")
        documents = payload.get("documents", [])
        if int(payload.get("document_count", -1)) != len(documents):
            raise LexicalIndexError("lexical index document count is corrupt")
        expected_chunk_uids = {
            row["evidence_uid"]
            for row in store.connection.execute(
                "SELECT evidence_uid FROM snapshot_membership WHERE domain=? AND scope_id=? AND snapshot_id=? AND evidence_kind='chunk'",
                (payload["domain"], payload["scope_id"], payload["generation_id"]),
            )
        }
        if expected_chunk_uids != {str(item.get("chunk_uid")) for item in documents}:
            raise LexicalIndexError("lexical index does not cover the exact generation chunk corpus")
        observed_df: Counter[str] = Counter()
        observed_total = 0
        for document in documents:
            row = store.connection.execute(
                "SELECT payload_json,object_uid,object_revision_uid FROM chunks WHERE domain=? AND scope_id=? AND chunk_uid=?",
                (payload["domain"], payload["scope_id"], document["chunk_uid"]),
            ).fetchone()
            if row is None:
                raise LexicalIndexError("lexical index references missing chunk")
            if row["object_uid"] != document.get("object_uid") or row["object_revision_uid"] != document.get("object_revision_uid"):
                raise LexicalIndexError("lexical index chunk identity is corrupt")
            chunk = json.loads(row["payload_json"])
            text = str(chunk["text"])
            content_hash = sha256(text.encode("utf-8")).hexdigest()
            if content_hash != document.get("content_hash") or content_hash != chunk.get("content_hash"):
                raise LexicalIndexError("lexical index text hash mismatch")
            tokens = tokenizer.tokens(text)
            if list(tokens) != document.get("tokens") or len(tokens) != int(document.get("token_count", -1)):
                raise LexicalIndexError("persisted lexical tokenization does not match validated text")
            observed_total += len(tokens)
            for term in set(tokens):
                observed_df[term] += 1
        if dict(sorted(observed_df.items())) != payload.get("df", {}):
            raise LexicalIndexError("lexical index document-frequency state is corrupt")
        expected_avg = observed_total / len(documents) if documents else 0.0
        if not math.isclose(float(payload.get("avgdl", -1.0)), expected_avg, rel_tol=0.0, abs_tol=1e-12):
            raise LexicalIndexError("lexical index average length is corrupt")
        return cls(store, path, payload, tokenizer)

    @property
    def artifact_sha256(self) -> str:
        return sha256(self.path.read_bytes()).hexdigest()

    def _validate_request(self, scope: ResolvedScope, snapshot: SnapshotRef) -> None:
        if (scope.domain, scope.scope_id, scope.corpus_id) != (self.domain, self.scope_id, self.corpus_id):
            raise LexicalIndexError("scope does not match lexical index")
        if (snapshot.domain, snapshot.scope_id) != (self.domain, self.scope_id):
            raise LexicalIndexError("snapshot scope does not match lexical index")
        if snapshot.snapshot_id != self.generation_id or snapshot.manifest_sha256 != self.manifest_sha256:
            raise LexicalIndexError("snapshot does not match lexical generation")

    def _live_chunk_allowed(self, chunk_uid: str, object_uid: str) -> bool:
        tombstone = self.store.connection.execute(
            "SELECT 1 FROM tombstones WHERE domain=? AND scope_id=? AND (evidence_uid=? OR evidence_uid=?) LIMIT 1",
            (self.domain, self.scope_id, chunk_uid, object_uid),
        ).fetchone()
        if tombstone is not None:
            return False
        withdrawn = self.store.connection.execute(
            "SELECT 1 FROM object_revisions WHERE domain=? AND scope_id=? AND object_uid=? AND lifecycle_state IN ('revoked','deleted') LIMIT 1",
            (self.domain, self.scope_id, object_uid),
        ).fetchone()
        return withdrawn is None

    def search(self, query: str, *, scope: ResolvedScope, snapshot: SnapshotRef, top_k: int = 20) -> tuple[BackendHit, ...]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self._validate_request(scope, snapshot)
        query_tokens = self.tokenizer.tokens(query)
        if not query_tokens or not self.docs:
            return ()
        qterms = tuple(dict.fromkeys(query_tokens))
        scores: list[tuple[float, dict[str, Any]]] = []
        n_docs = len(self.docs)
        for document in self.docs:
            if not self._live_chunk_allowed(document["chunk_uid"], document["object_uid"]):
                continue
            tf = Counter(document["tokens"])
            dl = len(document["tokens"])
            score = 0.0
            for term in qterms:
                freq = tf.get(term, 0)
                if freq <= 0:
                    continue
                doc_freq = self.df.get(term, 0)
                if doc_freq <= 0:
                    continue
                idf = math.log((n_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
                length_norm = self.b * dl / self.avgdl if self.avgdl else 0.0
                denominator = freq + self.k1 * (1.0 - self.b + length_norm)
                score += idf * (freq * (self.k1 + 1.0) / denominator)
            if score > 0.0:
                scores.append((score, document))
        scores.sort(key=lambda item: (-item[0], item[1]["chunk_uid"]))
        return tuple(
            BackendHit(
                backend_key=f"lexical:{self.generation_id}:{document['chunk_uid']}",
                domain=self.domain,
                scope_id=self.scope_id,
                snapshot_id=self.generation_id,
                logical_uid=document["chunk_uid"],
                raw_score=score,
                metadata={"rank": rank, "object_uid": document["object_uid"], "object_revision_uid": document["object_revision_uid"], "score_kind": "bm25"},
            )
            for rank, (score, document) in enumerate(scores[:top_k], start=1)
        )

    def hydrate(self, hit: BackendHit, *, scope: ResolvedScope, snapshot: SnapshotRef, policy: Any) -> str:
        self._validate_request(scope, snapshot)
        if (hit.domain, hit.scope_id, hit.snapshot_id) != (self.domain, self.scope_id, self.generation_id):
            raise LexicalIndexError("backend hit scope/generation does not match lexical index")
        document = next((item for item in self.docs if item["chunk_uid"] == hit.logical_uid), None)
        if document is None:
            raise LexicalIndexError("hit is not part of this lexical generation")
        if not self._live_chunk_allowed(document["chunk_uid"], document["object_uid"]):
            raise PermissionError("chunk is withdrawn under the live catalog overlay")
        member = self.store.connection.execute(
            "SELECT 1 FROM snapshot_membership WHERE domain=? AND scope_id=? AND snapshot_id=? AND evidence_kind='chunk' AND evidence_uid=?",
            (self.domain, self.scope_id, self.generation_id, hit.logical_uid),
        ).fetchone()
        if member is None:
            raise LexicalIndexError("chunk is no longer a member of the pinned generation")
        row = self.store.connection.execute(
            "SELECT payload_json FROM chunks WHERE domain=? AND scope_id=? AND chunk_uid=?",
            (self.domain, self.scope_id, hit.logical_uid),
        ).fetchone()
        if row is None:
            raise LexicalIndexError("chunk disappeared from catalog")
        chunk = json.loads(row["payload_json"])
        policy_payload = chunk.get("policy") or {}
        view = AuthorizedEvidenceView(
            evidence_uid=hit.logical_uid,
            domain=self.domain,
            scope_id=self.scope_id,
            source_instances=tuple(policy_payload.get("source_instances", ())),
            policy=EvidencePolicyMetadata.model_validate(policy_payload),
        )
        require_authorized(policy.authorize_evidence(view, scope, "caller"))
        return str(chunk["text"])


__all__ = ["LexicalIndex", "LexicalIndexError"]
