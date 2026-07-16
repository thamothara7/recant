"""TitanEmbedder must fit the Embedder protocol exactly, reach Bedrock only on
embed() (never on import or construction), and produce the request shape the
verified live invoke uses. Selection and threshold helpers are the single source
of truth shared by the fleet write path and the taint engine."""

import io
import json

import pytest

from services.common.embedder import (
    DIMENSIONS,
    HashEmbedder,
    TitanEmbedder,
    active_threshold,
    select_embedder,
)


class _FakeBody:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._raw


class _FakeBedrock:
    """Records the last invoke_model call and returns a canned embedding."""

    def __init__(self, vector):
        self.vector = vector
        self.calls: list[dict] = []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        return {"body": _FakeBody({"embedding": self.vector, "inputTextTokenCount": 3})}


def test_embed_returns_vector_and_sends_expected_request():
    fake = _FakeBedrock([0.01] * DIMENSIONS)
    emb = TitanEmbedder(client=fake)
    out = emb.embed("the refund window is 30 days")
    assert out == [0.01] * DIMENSIONS
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["modelId"] == "amazon.titan-embed-text-v2:0"
    body = json.loads(call["body"])
    assert body == {
        "inputText": "the refund window is 30 days",
        "dimensions": DIMENSIONS,
        "normalize": True,
    }


def test_embed_rejects_wrong_dimension():
    emb = TitanEmbedder(client=_FakeBedrock([0.0] * 512))
    with pytest.raises(ValueError, match="512 dims"):
        emb.embed("some text")


def test_embed_rejects_text_with_no_tokens():
    fake = _FakeBedrock([0.0] * DIMENSIONS)
    emb = TitanEmbedder(client=fake)
    with pytest.raises(ValueError, match="no alphanumeric tokens"):
        emb.embed("   !!!   ")
    # Must reject before reaching Bedrock.
    assert fake.calls == []


def test_construction_does_not_touch_aws():
    # No client injected and no boto3 call: constructing must not build a client.
    emb = TitanEmbedder()
    assert emb._client is None


def test_selection_returns_titan(monkeypatch):
    monkeypatch.setenv("RECANT_EMBEDDER", "titan")
    picked = select_embedder()
    assert isinstance(picked, TitanEmbedder)
    assert picked._client is None  # lazy: selection alone never reaches AWS


def test_active_threshold_tracks_selected_embedder(monkeypatch):
    monkeypatch.delenv("RECANT_TAINT_THRESHOLD", raising=False)
    monkeypatch.setenv("RECANT_EMBEDDER", "hash")
    assert active_threshold() == HashEmbedder.default_threshold
    monkeypatch.setenv("RECANT_EMBEDDER", "titan")
    assert active_threshold() == TitanEmbedder.default_threshold
    monkeypatch.delenv("RECANT_EMBEDDER", raising=False)
    assert active_threshold() == HashEmbedder.default_threshold


def test_taint_threshold_override_wins(monkeypatch):
    monkeypatch.setenv("RECANT_EMBEDDER", "titan")
    monkeypatch.setenv("RECANT_TAINT_THRESHOLD", "0.5")
    assert active_threshold() == 0.5
