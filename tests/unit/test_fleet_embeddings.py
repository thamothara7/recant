"""The LangChain adapter must be a pure delegate: deterministic, unit-norm,
and embed_query identical to a single-item embed_documents. The working-memory
store's behavior is exactly the Embedder protocol's behavior."""

import math
import os

import pytest

from fleet.embeddings import LangChainEmbedder, select_embedder
from services.common.embedder import DIMENSIONS, HashEmbedder, cosine


def test_delegates_to_inner_embedder():
    adapter = LangChainEmbedder(HashEmbedder())
    direct = HashEmbedder().embed("the refund window is thirty days")
    via_adapter = adapter.embed_query("the refund window is thirty days")
    assert via_adapter == direct


def test_deterministic_and_unit_norm():
    adapter = LangChainEmbedder()
    a = adapter.embed_query("standard refund window")
    b = adapter.embed_query("standard refund window")
    assert a == b
    assert len(a) == DIMENSIONS
    assert math.isclose(math.sqrt(sum(v * v for v in a)), 1.0, rel_tol=1e-9)


def test_embed_query_equals_single_item_embed_documents():
    adapter = LangChainEmbedder()
    text = "refunds over 500 USD require manager approval"
    assert adapter.embed_documents([text]) == [adapter.embed_query(text)]


def test_overlapping_texts_score_higher_than_unrelated():
    adapter = LangChainEmbedder()
    base = adapter.embed_query("extend refunds up to a year")
    overlap = adapter.embed_query("we extend refunds for a year")
    unrelated = adapter.embed_query("nightly batch scheduler maintenance")
    assert cosine(base, overlap) > cosine(base, unrelated)


def test_selection_is_env_driven(monkeypatch):
    monkeypatch.setenv("RECANT_EMBEDDER", "hash")
    assert isinstance(select_embedder(), HashEmbedder)
    monkeypatch.setenv("RECANT_EMBEDDER", "nonsense")
    with pytest.raises(ValueError):
        select_embedder()
    monkeypatch.delenv("RECANT_EMBEDDER", raising=False)
    assert isinstance(select_embedder(), HashEmbedder)
    assert os.environ.get("RECANT_EMBEDDER") is None
