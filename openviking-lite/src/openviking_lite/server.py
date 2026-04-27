"""HTTP server implementing the subset of the OpenViking API our gateway uses.

Endpoints
---------

- ``GET  /api/v1/health``                          → ``{"status":"ok"}``
- ``POST /api/v1/sessions``                        → create session, return id
- ``POST /api/v1/sessions/{sid}/messages``         → store one message
- ``POST /api/v1/sessions/{sid}/extract``          → no-op extraction stub
- ``DELETE /api/v1/sessions/{sid}``                → drop session + its messages
- ``POST /api/v1/resources/temp_upload``           → store a multipart file
- ``POST /api/v1/resources``                       → register a resource (idempotent)
- ``GET  /api/v1/resources``                       → list resources (optional ?account=)
- ``POST /api/v1/search``                          → FTS5 query across resources + messages

Auth: ``X-API-Key`` must match the configured key. ``X-OpenViking-Account`` and
``X-OpenViking-User`` are stored alongside content.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiohttp import web

from openviking_lite.db import DB
from openviking_lite.embeddings import EmbeddingProvider, encode, topk_brute

log = logging.getLogger(__name__)


def build_app(
    db: DB,
    api_key: str,
    embedding_provider: EmbeddingProvider | None = None,
) -> web.Application:
    app = web.Application(client_max_size=50 * 1024 * 1024)
    app["db"] = db
    app["api_key"] = api_key
    app["embed"] = embedding_provider

    app.middlewares.append(_auth_middleware)

    app.router.add_get("/api/v1/health", _handle_health)
    app.router.add_post("/api/v1/sessions", _handle_create_session)
    app.router.add_post("/api/v1/sessions/{sid}/messages", _handle_add_message)
    app.router.add_post("/api/v1/sessions/{sid}/extract", _handle_extract)
    app.router.add_delete("/api/v1/sessions/{sid}", _handle_delete_session)
    app.router.add_post("/api/v1/resources/temp_upload", _handle_temp_upload)
    app.router.add_post("/api/v1/resources", _handle_resource)
    app.router.add_get("/api/v1/resources", _handle_list_resources)
    app.router.add_post("/api/v1/search", _handle_search)
    return app


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

@web.middleware
async def _auth_middleware(request: web.Request, handler):
    if request.path == "/api/v1/health":
        return await handler(request)

    expected = request.app["api_key"]
    provided = request.headers.get("X-API-Key", "")
    if not expected:
        # Server has no key configured — fail closed.
        return web.json_response({"error": "server has no API key"}, status=503)
    if provided != expected:
        return web.json_response({"error": "unauthorised"}, status=401)
    return await handler(request)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _handle_health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def _handle_create_session(request: web.Request) -> web.Response:
    db: DB = request.app["db"]
    account = request.headers.get("X-OpenViking-Account", "default")
    user = request.headers.get("X-OpenViking-User", "anonymous")
    sid = await asyncio.to_thread(db.create_session, account, user)
    return web.json_response({"result": {"session_id": sid}})


async def _handle_add_message(request: web.Request) -> web.Response:
    db: DB = request.app["db"]
    embed: EmbeddingProvider | None = request.app["embed"]
    account = request.headers.get("X-OpenViking-Account", "default")
    sid = request.match_info["sid"]
    if not await asyncio.to_thread(db.session_exists, sid):
        return web.json_response({"error": "unknown session"}, status=404)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "invalid json"}, status=400)
    role = body.get("role", "user")
    content = body.get("content", "")
    meta = body.get("meta", "")
    if not content:
        return web.json_response({"error": "missing content"}, status=400)
    rowid = await asyncio.to_thread(db.add_message, sid, role, content, str(meta))

    if embed and embed.configured:
        vec = await embed.embed(content)
        if vec:
            await asyncio.to_thread(
                db.upsert_embedding, "message", f"{sid}:{rowid}", account, content, encode(vec)
            )
    return web.json_response({"result": "ok"})


async def _handle_extract(request: web.Request) -> web.Response:
    """No-op extraction: returns empty list. Real OpenViking runs an LLM here.

    Stub keeps the gateway happy — it gates on HTTP 200 and an iterable result.
    The actual semantic recall in this implementation is via FTS5 search over
    accumulated messages and resources.
    """
    db: DB = request.app["db"]
    sid = request.match_info["sid"]
    if not await asyncio.to_thread(db.session_exists, sid):
        return web.json_response({"error": "unknown session"}, status=404)
    return web.json_response({"result": []})


async def _handle_delete_session(request: web.Request) -> web.Response:
    db: DB = request.app["db"]
    sid = request.match_info["sid"]
    await asyncio.to_thread(db.delete_session, sid)
    return web.json_response({"result": "ok"})


async def _handle_temp_upload(request: web.Request) -> web.Response:
    db: DB = request.app["db"]
    account = request.headers.get("X-OpenViking-Account", "default")
    user = request.headers.get("X-OpenViking-User", "anonymous")

    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return web.json_response({"error": "expected multipart 'file' field"}, status=400)
    filename = field.filename or "unnamed"
    body_chunks: list[bytes] = []
    while True:
        chunk = await field.read_chunk(size=64 * 1024)
        if not chunk:
            break
        body_chunks.append(chunk)
    body = b"".join(body_chunks)

    temp_id = await asyncio.to_thread(db.store_temp_upload, account, user, filename, body)
    return web.json_response({"temp_file_id": temp_id})


async def _handle_resource(request: web.Request) -> web.Response:
    """Register a resource from a previously-uploaded temp file."""
    db: DB = request.app["db"]
    account = request.headers.get("X-OpenViking-Account", "default")
    user = request.headers.get("X-OpenViking-User", "anonymous")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "invalid json"}, status=400)
    temp_id = body.get("temp_file_id", "")
    uri = body.get("to", "")
    if not temp_id or not uri:
        return web.json_response({"error": "missing temp_file_id or to"}, status=400)

    consumed = await asyncio.to_thread(db.consume_temp_upload, temp_id)
    if not consumed:
        return web.json_response({"error": "unknown temp_file_id"}, status=404)
    _, raw = consumed
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        text = ""
    await asyncio.to_thread(db.upsert_resource, account, user, uri, text)

    embed: EmbeddingProvider | None = request.app["embed"]
    if embed and embed.configured and text:
        vec = await embed.embed(text)
        if vec:
            await asyncio.to_thread(
                db.upsert_embedding, "resource", uri, account, text, encode(vec)
            )
    return web.json_response({"status": "ok", "uri": uri})


async def _handle_list_resources(request: web.Request) -> web.Response:
    db: DB = request.app["db"]
    account = request.query.get("account")
    rows = await asyncio.to_thread(db.list_resources, account)
    return web.json_response({"resources": rows})


async def _handle_search(request: web.Request) -> web.Response:
    """Hybrid search across resources and messages.

    Body: ``{
        "query": "...",
        "kind":  "resources|messages|both",      // default "resources"
        "mode":  "fts5|semantic|hybrid",         // default "hybrid" if embed configured else "fts5"
        "limit": 20,
        "account": ""
    }``

    - ``fts5``     — keyword/lexical search via SQLite FTS5 (BM25).
    - ``semantic`` — cosine similarity against query embedding (requires embed provider).
    - ``hybrid``   — both; results are union'd, ranked by 0.5*BM25_norm + 0.5*cosine.
    """
    db: DB = request.app["db"]
    embed: EmbeddingProvider | None = request.app["embed"]
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "invalid json"}, status=400)
    query = body.get("query", "")
    if not query:
        return web.json_response({"error": "missing query"}, status=400)
    kind = body.get("kind", "resources")
    limit = int(body.get("limit", 20))
    account = body.get("account") or request.headers.get("X-OpenViking-Account")
    mode = body.get("mode") or ("hybrid" if (embed and embed.configured) else "fts5")

    if mode in ("semantic", "hybrid") and (embed is None or not embed.configured):
        return web.json_response(
            {"error": "semantic mode requested but no embedding provider configured"},
            status=400,
        )

    out: dict[str, list] = {"mode": mode}

    query_vec = None
    if mode in ("semantic", "hybrid"):
        query_vec = await embed.embed(query)  # type: ignore[union-attr]
        if not query_vec:
            return web.json_response({"error": "embed request failed"}, status=502)

    for k in ("resources", "messages"):
        if kind not in (k, "both"):
            continue
        fts_hits = []
        sem_hits = []
        if mode in ("fts5", "hybrid"):
            if k == "resources":
                fts_hits = await asyncio.to_thread(db.search_resources, query, account, limit)
            else:
                fts_hits = await asyncio.to_thread(db.search_messages, query, limit)
        if mode in ("semantic", "hybrid"):
            assert query_vec is not None
            cands = await asyncio.to_thread(
                db.candidate_embeddings,
                kind=("resource" if k == "resources" else "message"),
                account=account,
            )
            simple = [(ref_id, blob) for ref_id, blob, _ in cands]
            ranked = topk_brute(query_vec, simple, k=limit)
            cand_index = {ref_id: content for ref_id, _, content in cands}
            sem_hits = [{"ref_id": rid, "score": s, "content": cand_index.get(rid, "")}
                        for rid, s in ranked]

        if mode == "fts5":
            out[k] = fts_hits
        elif mode == "semantic":
            out[k] = sem_hits
        else:  # hybrid: union by content, simple 0.5/0.5 score normalisation
            out[k] = _hybrid_merge(fts_hits, sem_hits, k, limit)

    return web.json_response(out)


def _hybrid_merge(fts_hits, sem_hits, kind, limit):
    """Combine FTS5 BM25 (rank ascending = better) with cosine (descending)."""
    # Normalise FTS5 rank: lower rank → higher score. Take 1 / (1 + rank).
    by_content: dict[str, dict] = {}
    for h in fts_hits:
        c = h.get("content", "")
        rank = float(h.get("rank", 0.0)) if h.get("rank") is not None else 0.0
        fts_score = 1.0 / (1.0 + abs(rank))
        ref_id = h.get("uri") or h.get("session_id") or c[:64]
        by_content[c] = {
            "ref_id": ref_id, "content": c, "fts_score": fts_score, "sem_score": 0.0
        }
    for h in sem_hits:
        c = h.get("content", "")
        sem_score = float(h.get("score", 0.0))
        if c in by_content:
            by_content[c]["sem_score"] = sem_score
        else:
            by_content[c] = {
                "ref_id": h.get("ref_id", ""), "content": c,
                "fts_score": 0.0, "sem_score": sem_score,
            }
    rows = list(by_content.values())
    for r in rows:
        r["score"] = 0.5 * r["fts_score"] + 0.5 * r["sem_score"]
    rows.sort(key=lambda r: -r["score"])
    return rows[:limit]


def serve(
    host: str,
    port: int,
    db_path: Path,
    key_path: Path,
    *,
    openai_key_path: Path | None = None,
    openai_model: str = "text-embedding-3-small",
) -> None:
    api_key = key_path.read_text().strip() if key_path.exists() else ""
    db = DB(db_path)

    embed: EmbeddingProvider | None = None
    if openai_key_path and openai_key_path.exists():
        oai_key = openai_key_path.read_text().strip()
        if oai_key:
            embed = EmbeddingProvider(api_key=oai_key, model=openai_model)
            log.info("openviking-lite: OpenAI embeddings enabled (model=%s)", openai_model)
        else:
            log.warning("openviking-lite: OpenAI key file empty — embeddings disabled")
    else:
        log.info("openviking-lite: no OpenAI key — running FTS5-only")

    app = build_app(db, api_key, embed)
    log.info("openviking-lite serving on %s:%d (db=%s)", host, port, db_path)
    web.run_app(app, host=host, port=port, print=lambda *_: None)
