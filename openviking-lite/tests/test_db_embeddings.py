"""DB-level embedding tests."""

from __future__ import annotations

from pathlib import Path

from openviking_lite.db import DB
from openviking_lite.embeddings import encode, topk_brute


def test_upsert_and_recall(tmp_path: Path):
    db = DB(tmp_path / "ov.db")
    db.upsert_embedding("resource", "viking://r/1", "acme", "ferns", encode([1.0, 0.0, 0.0]))
    db.upsert_embedding("resource", "viking://r/2", "acme", "cacti", encode([0.0, 1.0, 0.0]))
    cands = db.candidate_embeddings(kind="resource", account="acme")
    assert len(cands) == 2
    ids = {ref for ref, _, _ in cands}
    assert ids == {"viking://r/1", "viking://r/2"}


def test_upsert_replaces_existing(tmp_path: Path):
    db = DB(tmp_path / "ov.db")
    db.upsert_embedding("resource", "viking://r/1", "acme", "v1", encode([1.0, 0.0]))
    db.upsert_embedding("resource", "viking://r/1", "acme", "v2", encode([0.0, 1.0]))
    cands = db.candidate_embeddings(kind="resource", account="acme")
    assert len(cands) == 1
    assert cands[0][2] == "v2"


def test_account_isolation(tmp_path: Path):
    db = DB(tmp_path / "ov.db")
    db.upsert_embedding("resource", "viking://a", "alpha", "alpha-content", encode([1.0]))
    db.upsert_embedding("resource", "viking://b", "beta",  "beta-content",  encode([1.0]))
    a = db.candidate_embeddings(kind="resource", account="alpha")
    b = db.candidate_embeddings(kind="resource", account="beta")
    assert len(a) == 1 and a[0][2] == "alpha-content"
    assert len(b) == 1 and b[0][2] == "beta-content"


def test_kind_isolation(tmp_path: Path):
    db = DB(tmp_path / "ov.db")
    db.upsert_embedding("message",  "sid:1",         "acme", "msg",  encode([1.0]))
    db.upsert_embedding("resource", "viking://r/x",  "acme", "res",  encode([0.0]))
    msgs = db.candidate_embeddings(kind="message", account="acme")
    res = db.candidate_embeddings(kind="resource", account="acme")
    assert len(msgs) == 1 and msgs[0][2] == "msg"
    assert len(res) == 1 and res[0][2] == "res"


def test_message_returns_rowid(tmp_path: Path):
    db = DB(tmp_path / "ov.db")
    sid = db.create_session("acme", "u")
    rowid_a = db.add_message(sid, "user", "first")
    rowid_b = db.add_message(sid, "user", "second")
    assert rowid_a > 0 and rowid_b > 0
    assert rowid_a != rowid_b


def test_topk_against_db_candidates(tmp_path: Path):
    db = DB(tmp_path / "ov.db")
    db.upsert_embedding("resource", "v://near",   "acme", "near",   encode([0.95, 0.1, 0.0]))
    db.upsert_embedding("resource", "v://middle", "acme", "middle", encode([0.5, 0.5, 0.0]))
    db.upsert_embedding("resource", "v://far",    "acme", "far",    encode([0.0, 1.0, 0.0]))
    cands = [(ref, blob) for ref, blob, _ in
             db.candidate_embeddings(kind="resource", account="acme")]
    top = topk_brute([1.0, 0.0, 0.0], cands, k=2)
    assert top[0][0] == "v://near"
    assert top[1][0] == "v://middle"
