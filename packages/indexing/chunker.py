"""Deterministic field-aware chunking for immutable evidence revisions."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any, Iterable, Mapping

from packages.evidence.ids import canonical_hash, canonical_json, chunk_uid
from packages.evidence.schema import EvidenceChunk, EvidenceExtension, EvidenceObject

_TOKEN_RE = re.compile(
    r"CVE-\d{4}-\d{4,}|CWE-\d+|CAPEC-\d+|T\d{4}(?:\.\d{3})?|"
    r"[A-Za-z0-9][A-Za-z0-9._:+/@-]*|[\u3400-\u4dbf\u4e00-\u9fff]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TokenSpan:
    token: str
    start: int
    end: int


class DeterministicTokenizer:
    name = "regex-cti-unicode-v1"

    @property
    def fingerprint(self) -> str:
        return canonical_hash(["tokenizer-v1", self.name, _TOKEN_RE.pattern])

    def spans(self, text: str) -> tuple[TokenSpan, ...]:
        return tuple(
            TokenSpan(match.group(0).casefold(), match.start(), match.end())
            for match in _TOKEN_RE.finditer(text)
        )

    def tokens(self, text: str) -> tuple[str, ...]:
        return tuple(item.token for item in self.spans(text))


@dataclass(frozen=True)
class ChunkingConfig:
    target_tokens: int = 450
    overlap_tokens: int = 75

    def __post_init__(self) -> None:
        if self.target_tokens < 1:
            raise ValueError("target_tokens must be positive")
        if self.overlap_tokens < 0 or self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens must satisfy 0 <= overlap < target_tokens")

    @property
    def fingerprint(self) -> str:
        return canonical_hash(["chunker-v1", self.target_tokens, self.overlap_tokens])


_DEFAULT_ORDER = ("name", "external_ids", "aliases", "description", "family_data")


def _field_text(obj: EvidenceObject, field_name: str) -> str:
    value = getattr(obj, field_name, None)
    if value is None:
        return ""
    if field_name == "external_ids":
        return " ".join(
            f"{item.namespace}:{item.value}" + (f" version:{item.version}" if item.version else "")
            for item in value
        )
    if field_name == "aliases":
        return "\n".join(str(item) for item in value)
    if hasattr(value, "model_dump"):
        return canonical_json(value.model_dump(mode="json"))
    if isinstance(value, (tuple, list, dict)):
        return canonical_json(value)
    return str(value)


def _section_order(hints: Mapping[str, str] | None) -> tuple[str, ...]:
    if not hints:
        return _DEFAULT_ORDER
    preferred = [name for name in _DEFAULT_ORDER if name in hints]
    extra = sorted(name for name in hints if name not in preferred and not name.startswith("_"))
    return tuple((*preferred, *extra))


def _extension(segments: list[dict[str, Any]]) -> EvidenceExtension:
    return EvidenceExtension(
        type_name="chunk-source-offsets",
        schema_version="v1",
        data={"segments": segments},
    )


def _make_chunk(
    *,
    obj: EvidenceObject,
    text: str,
    section_path: str,
    ordinal: int,
    segments: list[dict[str, Any]],
    token_count: int,
    tokenizer: DeterministicTokenizer,
    config: ChunkingConfig,
    chunk_class: type[EvidenceChunk],
) -> EvidenceChunk:
    content_hash = sha256(text.encode("utf-8")).hexdigest()
    uid = chunk_uid(
        object_id=obj.uid,
        object_revision_id=obj.revision_uid,
        chunker_fingerprint=config.fingerprint,
        section_path=section_path,
        ordinal=ordinal,
        content_hash=content_hash,
    )
    return chunk_class(
        uid=uid,
        object_uid=obj.uid,
        object_revision_uid=obj.revision_uid,
        domain=obj.domain,
        scope_id=obj.scope_id,
        chunker_fingerprint=config.fingerprint,
        section_path=section_path,
        ordinal=ordinal,
        text=text,
        content_hash=content_hash,
        token_count=len(tokenizer.tokens(text)),
        tokenizer_fingerprint=tokenizer.fingerprint,
        source_refs=obj.source_refs,
        policy=obj.policy,
        extension_type=f"{obj.domain}-chunk",
        extension=_extension(segments),
    )


def chunk_object(
    obj: EvidenceObject,
    *,
    serialization_hints: Mapping[str, str] | None = None,
    tokenizer: DeterministicTokenizer | None = None,
    config: ChunkingConfig = ChunkingConfig(),
    chunk_class: type[EvidenceChunk] = EvidenceChunk,
) -> tuple[EvidenceChunk, ...]:
    tokenizer = tokenizer or DeterministicTokenizer()
    sections: list[tuple[str, str, tuple[TokenSpan, ...]]] = []
    for field_name in _section_order(serialization_hints):
        text = _field_text(obj, field_name)
        if not text:
            continue
        spans = tokenizer.spans(text)
        if spans:
            sections.append((field_name, text, spans))

    if not sections:
        return ()

    total_tokens = sum(len(spans) for _, _, spans in sections)
    if total_tokens <= config.target_tokens:
        parts: list[str] = []
        segments: list[dict[str, Any]] = []
        emitted = 0
        for field_name, text, spans in sections:
            prefix = f"[{field_name}]\n"
            if parts:
                parts.append("\n")
                emitted += 1
            parts.append(prefix)
            emitted += len(prefix)
            text_start = emitted
            parts.append(text)
            emitted += len(text)
            segments.append(
                {
                    "field": field_name,
                    "source_start": 0,
                    "source_end": len(text),
                    "emitted_start": text_start,
                    "emitted_end": emitted,
                }
            )
        joined = "".join(parts)
        return (
            _make_chunk(
                obj=obj,
                text=joined,
                section_path="object",
                ordinal=0,
                segments=segments,
                token_count=total_tokens,
                tokenizer=tokenizer,
                config=config,
                chunk_class=chunk_class,
            ),
        )

    chunks: list[EvidenceChunk] = []
    ordinal = 0
    stride = config.target_tokens - config.overlap_tokens
    for field_name, text, spans in sections:
        start_token = 0
        while start_token < len(spans):
            end_token = min(start_token + config.target_tokens, len(spans))
            window = spans[start_token:end_token]
            char_start = window[0].start
            char_end = window[-1].end
            emitted = text[char_start:char_end]
            chunks.append(
                _make_chunk(
                    obj=obj,
                    text=emitted,
                    section_path=field_name,
                    ordinal=ordinal,
                    segments=[
                        {
                            "field": field_name,
                            "source_start": char_start,
                            "source_end": char_end,
                            "emitted_start": 0,
                            "emitted_end": len(emitted),
                        }
                    ],
                    token_count=len(window),
                    tokenizer=tokenizer,
                    config=config,
                    chunk_class=chunk_class,
                )
            )
            ordinal += 1
            if end_token == len(spans):
                break
            start_token += stride
    return tuple(chunks)


def chunk_objects(
    objects: Iterable[EvidenceObject],
    *,
    serialization_hints: Mapping[str, str] | None = None,
    tokenizer: DeterministicTokenizer | None = None,
    config: ChunkingConfig = ChunkingConfig(),
    chunk_class: type[EvidenceChunk] = EvidenceChunk,
) -> tuple[EvidenceChunk, ...]:
    tokenizer = tokenizer or DeterministicTokenizer()
    return tuple(
        chunk
        for obj in objects
        for chunk in chunk_object(
            obj,
            serialization_hints=serialization_hints,
            tokenizer=tokenizer,
            config=config,
            chunk_class=chunk_class,
        )
    )


__all__ = ["ChunkingConfig", "DeterministicTokenizer", "TokenSpan", "chunk_object", "chunk_objects"]
