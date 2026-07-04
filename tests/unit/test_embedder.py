import math

import pytest

from services.common.embedder import DIMENSIONS, HashEmbedder, cosine


def test_dimensions_and_unit_norm():
    v = HashEmbedder().embed("The standard refund window is 30 days.")
    assert len(v) == DIMENSIONS
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-9)


def test_deterministic_across_instances():
    a = HashEmbedder().embed("refund window")
    b = HashEmbedder().embed("refund window")
    assert a == b


def test_case_and_punctuation_insensitive_tokens():
    e = HashEmbedder()
    assert e.embed("Refund Window!") == e.embed("refund window")


def test_similarity_orders_by_token_overlap():
    e = HashEmbedder()
    poisoned = e.embed("the refund window is 365 days")
    paraphrase = e.embed("the refund window is now 365 days for everyone")
    unrelated = e.embed("partner status api is operational tonight")
    assert cosine(poisoned, paraphrase) > 0.7
    assert cosine(poisoned, unrelated) < 0.3
    assert cosine(poisoned, paraphrase) > cosine(poisoned, unrelated)


def test_identical_text_similarity_is_one():
    e = HashEmbedder()
    v = e.embed("quarantine every derived belief")
    assert math.isclose(cosine(v, v), 1.0, rel_tol=1e-9)


def test_empty_text_rejected():
    with pytest.raises(ValueError):
        HashEmbedder().embed("!!! --- ???")
