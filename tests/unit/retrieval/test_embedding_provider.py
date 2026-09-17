from __future__ import annotations

import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from packages.retrieval.providers import (
    DeterministicFixtureEmbeddingProvider,
    EmbeddingBatch,
    EmbeddingEgressDenied,
    EmbeddingFingerprint,
    EmbeddingFingerprintMismatch,
    EmbeddingInput,
    EmbeddingProviderRegistry,
    EmbeddingProviderUnavailable,
    EmbeddingValidationError,
    IndexedEmbedding,
    validate_embedding_batch,
)


def fp(**overrides):
    values = dict(
        provider="fixture",
        model="model-a",
        revision="rev-a",
        dimensions=4,
        metric="cosine",
        normalization="l2",
        document_instruction="doc",
        query_instruction="query",
        tokenizer="tok-v1",
        artifact_sha256="a" * 64,
        remote=False,
    )
    values.update(overrides)
    return EmbeddingFingerprint(**values)


def unit(v):
    norm = math.sqrt(sum(x * x for x in v))
    return tuple(x / norm for x in v)


def test_equal_dimension_different_models_have_distinct_fingerprints():
    assert fp(model="model-a").digest != fp(model="model-b").digest


def test_document_and_query_instructions_are_fingerprint_bound():
    assert fp(document_instruction="doc-a").digest != fp(document_instruction="doc-b").digest
    assert fp(query_instruction="query-a").digest != fp(query_instruction="query-b").digest


def test_output_mapping_is_reordered_but_must_be_complete():
    fingerprint = fp()
    batch = EmbeddingBatch(
        fingerprint=fingerprint,
        embeddings=(
            IndexedEmbedding(item_id="b", vector=unit((1, 2, 3, 4))),
            IndexedEmbedding(item_id="a", vector=unit((4, 3, 2, 1))),
        ),
    )
    result = validate_embedding_batch(batch, expected_ids=("a", "b"), expected_fingerprint=fingerprint)
    assert [item.item_id for item in result.embeddings] == ["a", "b"]

    with pytest.raises(EmbeddingValidationError, match="exactly"):
        validate_embedding_batch(
            EmbeddingBatch(fingerprint=fingerprint, embeddings=(batch.embeddings[0],)),
            expected_ids=("a", "b"),
            expected_fingerprint=fingerprint,
        )


def test_nan_dimension_and_fingerprint_mismatch_fail_closed():
    fingerprint = fp()
    with pytest.raises(Exception):
        IndexedEmbedding(item_id="a", vector=(float("nan"), 0.0, 0.0, 1.0))
    with pytest.raises(EmbeddingValidationError, match="dimension"):
        validate_embedding_batch(
            EmbeddingBatch(
                fingerprint=fingerprint,
                embeddings=(IndexedEmbedding(item_id="a", vector=unit((1.0, 2.0, 3.0))),),
            ),
            expected_ids=("a",),
            expected_fingerprint=fingerprint,
        )
    with pytest.raises(EmbeddingFingerprintMismatch, match="reindexed"):
        validate_embedding_batch(
            EmbeddingBatch(
                fingerprint=fp(model="model-b"),
                embeddings=(IndexedEmbedding(item_id="a", vector=unit((1.0, 2.0, 3.0, 4.0))),),
            ),
            expected_ids=("a",),
            expected_fingerprint=fingerprint,
        )


def test_unauthorized_destination_is_denied_before_encoding():
    provider = DeterministicFixtureEmbeddingProvider(dimensions=8)
    calls = {"vector": 0}
    original = provider._vector

    def counted(**kwargs):
        calls["vector"] += 1
        return original(**kwargs)

    provider._vector = counted  # type: ignore[method-assign]
    with pytest.raises(EmbeddingEgressDenied):
        provider.encode_documents(
            (EmbeddingInput(item_id="a", text="secret"),),
            destination="embedding_provider",
        )
    assert calls["vector"] == 0


def test_registry_never_falls_back_to_fixture_for_missing_real_provider():
    registry = EmbeddingProviderRegistry(
        {"fixture": lambda: DeterministicFixtureEmbeddingProvider(dimensions=8)}
    )
    with pytest.raises(EmbeddingProviderUnavailable):
        registry.create("local-real")


def test_import_is_sdk_and_network_inert_in_fresh_process():
    root = Path(__file__).resolve().parents[3]
    code = (
        "import sys; mods=('openai','zhipuai','FlagEmbedding','sentence_transformers','requests','httpx'); "
        "before={m:(m in sys.modules) for m in mods}; import packages.retrieval.providers; "
        "print(' '.join(str(int((m in sys.modules) and not before[m])) for m in mods))"
    )
    env = {**os.environ, "PYTHONPATH": str(root)}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=root, env=env, text=True, capture_output=True, check=True
    )
    assert result.stdout.strip() == "0 0 0 0 0 0"


def test_fixture_vectors_stable_across_processes():
    root = Path(__file__).resolve().parents[3]
    code = (
        "from packages.retrieval.providers import DeterministicFixtureEmbeddingProvider,EmbeddingInput;"
        "p=DeterministicFixtureEmbeddingProvider(dimensions=8);"
        "b=p.encode_documents((EmbeddingInput(item_id='x',text='CVE-2026-999999'),),destination='local_generator');"
        "print(p.fingerprint.digest);print(','.join(format(x,'.17g') for x in b.embeddings[0].vector))"
    )
    env = {**os.environ, "PYTHONPATH": str(root)}
    a = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, text=True, capture_output=True, check=True)
    b = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, text=True, capture_output=True, check=True)
    assert a.stdout == b.stdout
