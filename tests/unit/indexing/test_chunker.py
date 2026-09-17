from __future__ import annotations

import pytest

from packages.domains.cti import CtiDomainAdapter, CtiChunk
from packages.indexing.chunker import ChunkingConfig, DeterministicTokenizer, chunk_object

from ._helpers import batch_and_raw


def test_small_object_stays_intact_and_is_deterministic():
    batch, _ = batch_and_raw()
    obj = batch.objects[0]
    tokenizer = DeterministicTokenizer()
    kwargs = {
        "serialization_hints": CtiDomainAdapter().field_serialization_hints(),
        "tokenizer": tokenizer,
        "chunk_class": CtiChunk,
    }
    first = chunk_object(obj, **kwargs)
    second = chunk_object(obj, **kwargs)
    assert first == second
    assert len(first) == 1
    assert isinstance(first[0], CtiChunk)
    assert first[0].object_revision_uid == obj.revision_uid
    assert first[0].effective_marking_refs == obj.marking_refs
    assert first[0].granular_selectors == obj.policy.granular_selectors
    assert first[0].citation_locator == "object"
    assert first[0].tokenizer_fingerprint == tokenizer.fingerprint
    assert first[0].content_hash
    assert "CVE-2026-999999" in first[0].text
    assert first[0].extension.data["segments"]


def test_long_prose_uses_target_overlap_and_preserves_source_offsets():
    batch, _ = batch_and_raw()
    obj = batch.objects[0]
    description = " ".join(f"word{i}" for i in range(34))
    obj = obj.model_copy(update={"description": description})
    tokenizer = DeterministicTokenizer()
    chunks = chunk_object(
        obj,
        serialization_hints={"description": "body"},
        tokenizer=tokenizer,
        config=ChunkingConfig(target_tokens=10, overlap_tokens=3),
        chunk_class=CtiChunk,
    )
    description_chunks = [chunk for chunk in chunks if chunk.section_path == "description"]
    assert len(description_chunks) >= 4
    assert len({chunk.uid for chunk in description_chunks}) == len(description_chunks)
    assert all(chunk.token_count <= 10 for chunk in description_chunks)
    previous_tokens = None
    for chunk in description_chunks:
        segment = chunk.extension.data["segments"][0]
        assert description[segment["source_start"]:segment["source_end"]] == chunk.text
        tokens = tokenizer.tokens(chunk.text)
        if previous_tokens is not None:
            assert tuple(previous_tokens[-3:]) == tuple(tokens[:3])
        previous_tokens = tokens


def test_tokenizer_preserves_whole_cti_identifiers_and_versions():
    tokenizer = DeterministicTokenizer()
    tokens = tokenizer.tokens("CVE-2026-999999 CWE-79 CAPEC-66 T1059.001 version 4.2")
    assert tokens[:4] == ("cve-2026-999999", "cwe-79", "capec-66", "t1059.001")
    assert "4.2" in tokens


def test_invalid_overlap_or_budget_fails_closed():
    with pytest.raises(ValueError, match="target_tokens"):
        ChunkingConfig(target_tokens=0, overlap_tokens=0)
    with pytest.raises(ValueError, match="overlap_tokens"):
        ChunkingConfig(target_tokens=10, overlap_tokens=10)
