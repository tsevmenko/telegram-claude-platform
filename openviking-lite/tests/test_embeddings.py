"""Embedding helpers — encoding, decoding, cosine similarity, top-k."""

from __future__ import annotations

from openviking_lite.embeddings import cosine, decode, encode, topk_brute


def test_encode_decode_roundtrip():
    vec = [0.1, -0.2, 0.3, 4.5]
    blob = encode(vec)
    assert isinstance(blob, bytes)
    assert len(blob) == 16  # 4 floats × 4 bytes
    out = decode(blob)
    for a, b in zip(vec, out):
        assert abs(a - b) < 1e-5


def test_cosine_orthogonal_is_zero():
    assert abs(cosine([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])) < 1e-9


def test_cosine_identical_is_one():
    v = [1.0, 2.0, 3.0]
    assert abs(cosine(v, v) - 1.0) < 1e-9


def test_cosine_opposite_is_minus_one():
    v = [1.0, 2.0, 3.0]
    w = [-1.0, -2.0, -3.0]
    assert abs(cosine(v, w) + 1.0) < 1e-9


def test_cosine_zero_vector_is_zero():
    assert cosine([0.0, 0.0, 0.0], [1.0, 1.0, 1.0]) == 0.0


def test_cosine_dim_mismatch_returns_zero():
    assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_topk_picks_closest():
    query = [1.0, 0.0, 0.0]
    candidates = [
        ("near",   encode([0.95, 0.1, 0.0])),
        ("far",    encode([0.0, 1.0, 0.0])),
        ("middle", encode([0.5, 0.5, 0.0])),
    ]
    top = topk_brute(query, candidates, k=2)
    assert len(top) == 2
    assert top[0][0] == "near"
    assert top[1][0] == "middle"


def test_topk_respects_k():
    query = [1.0, 0.0]
    candidates = [(f"v{i}", encode([1.0, float(i) / 10])) for i in range(10)]
    top = topk_brute(query, candidates, k=3)
    assert len(top) == 3
    # Scores are descending.
    assert top[0][1] >= top[1][1] >= top[2][1]
