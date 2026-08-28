from __future__ import annotations

import logging
import secrets as pysecrets
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from melt import config

from melt.db import (
    HashConflict,
    IdempotencyConflict,
    connect,
    delete_capture,
    ingest,
    init_db,
    mark_reuse,
    recency_list,
    search_sources,
    source_detail,
    source_matches_query,
    undo_latest,
    upsert_context,
)
from melt.i18n import t, load_catalog
from melt.normalize import NormalizeError, infer_kind, normalize, normalize_context
from melt.secrets import looks_like_secret

log = logging.getLogger("melt")
logging.basicConfig(level=logging.INFO)

ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(ROOT / "templates"))
TEMPLATES.env.autoescape = True

# `default-src 'self'` rejects inline <style>/<script>, so the inbox loads both
# from /static. Keep it that way when editing the templates.
CSP = "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"

DISPLAY_CHARS = 20_000
LOGIN_MAX = 4096
SIZE_OVERHEAD = 4096


class SizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        if request.url.path == "/v1/login":
            limit = LOGIN_MAX
        else:
            limit = config.max_bytes() + SIZE_OVERHEAD
        if length is not None:
            try:
                n = int(length)
            except ValueError:
                n = 0
            if n > limit:
                return JSONResponse(
                    status_code=413,
                    content=_problem(
                        "too_large", f"body exceeds {config.max_bytes()} bytes", 413
                    ),
                )
        return await call_next(request)


def _problem(code: str, detail: str, status: int) -> dict:
    return {
        "type": f"https://github.com/daaquan/melt/blob/main/docs/troubleshooting.md#{code}",
        "title": code,
        "status": status,
        "detail": detail,
        "code": code,
    }


def token_matches(given: str, expected: str) -> bool:
    """Constant-time compare.

    secrets.compare_digest raises TypeError on non-ASCII str, and both the login
    form and the cookie carry attacker-controlled text, so compare bytes.
    """
    if not expected:
        return False
    return pysecrets.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def get_conn():
    conn = connect(config.db_path())
    try:
        yield conn
    finally:
        conn.close()


def is_authed(request: Request, authorization: str | None) -> bool:
    token = config.token()
    if not token:
        return False
    if authorization and authorization.startswith("Bearer "):
        if token_matches(authorization.removeprefix("Bearer "), token):
            return True
    cookie = request.cookies.get(config.COOKIE_NAME, "")
    return bool(cookie) and token_matches(cookie, token)


def require_auth(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if not is_authed(request, authorization):
        raise HTTPException(status_code=401, detail=_problem("auth", "token mismatch", 401))


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.token():
        log.warning("MELT_TOKEN is empty; all auth will fail")
    init_db(config.db_path())
    app.state.catalog = load_catalog()
    yield


app = FastAPI(title="melt", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(SizeLimitMiddleware)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.exception_handler(HTTPException)
async def problem_response(request: Request, exc: HTTPException) -> JSONResponse:
    """Return the problem object itself, not FastAPI's {"detail": ...} wrapper.

    Routes and SizeLimitMiddleware then agree on one error shape, so a client
    can always read `code` off the top level.
    """
    body = (
        exc.detail
        if isinstance(exc.detail, dict)
        else _problem("error", str(exc.detail), exc.status_code)
    )
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    hostname = request.headers.get("host", "").split(":")[0]
    if hostname not in config.allowed_hosts():
        return JSONResponse(status_code=400, content=_problem("bad_host", "host not allowed", 400))
    response: Response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


class CaptureIn(BaseModel):
    kind: str | None = None
    body: str = Field(default="")


@app.post("/v1/captures")
def post_capture(
    payload: CaptureIn,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    authorization: Annotated[str | None, Header()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    require_auth(request, authorization)
    body = payload.body
    kind = payload.kind or infer_kind(body)
    if not config.allow_secrets() and looks_like_secret(body):
        raise HTTPException(
            status_code=400,
            detail=_problem("secret_blocked", "body looks like a secret", 400),
        )
    key = idempotency_key or str(uuid.uuid4())
    try:
        kind, normalized = normalize(kind, body)
    except NormalizeError as exc:
        status = 413 if exc.code == "too_large" else 400
        raise HTTPException(status_code=status, detail=_problem(exc.code, str(exc), status)) from exc
    try:
        result = ingest(
            conn,
            kind=kind,
            raw_body=body,
            normalized_body=normalized,
            idempotency_key=key,
        )
    except HashConflict:
        raise HTTPException(
            status_code=409,
            detail=_problem("conflict_hash", "hash collision with different body", 409),
        )
    except IdempotencyConflict:
        raise HTTPException(
            status_code=409,
            detail=_problem("conflict_idempotency", "Idempotency-Key reused with different body", 409),
        )
    except sqlite3.OperationalError:
        raise HTTPException(
            status_code=503,
            detail=_problem("disk_full", "sqlite operational error", 503),
        )
    log.info(
        "ingest capture_id=%s source_id=%s occ=%s",
        result["capture_id"],
        result["source_id"],
        result["occurrence_count"],
    )
    return JSONResponse(
        status_code=201,
        content={
            "capture_id": result["capture_id"],
            "source_id": result["source_id"],
            "occurrence_count": result["occurrence_count"],
            "digest_status": result["digest_status"],
        },
    )


@app.get("/v1/search")
def api_search(
    request: Request,
    q: str = "",
    conn: sqlite3.Connection = Depends(get_conn),
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    require_auth(request, authorization)
    rows = search_sources(conn, q) if q else []
    return {
        "hits": [
            {
                "source_id": row["source_id"],
                "captured_at": row["captured_at"],
                "occurrence_count": row["occ"],
            }
            for row in rows
        ]
    }


@app.get("/v1/sources/{source_id}")
def api_source(
    source_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    require_auth(request, authorization)
    detail = source_detail(conn, source_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=_problem("not_found", "source missing", 404))
    digest = detail["digest"]
    latest = detail["captures"][0] if detail["captures"] else None
    return {
        "source_id": source_id,
        "kind": detail["source"]["kind"],
        "raw_body": latest["raw_body"] if latest else "",
        "normalized_body": detail["source"]["normalized_body"],
        "digest": None
        if digest is None
        else {
            "summary": digest["summary"],
            "model": digest["model"],
            "prompt_id": digest["prompt_id"],
        },
        "captured_at": [row["captured_at"] for row in detail["captures"]],
        "context": detail["context"],
    }


class ContextIn(BaseModel):
    body: str = ""


def _prepare_context(raw: str) -> tuple[str | None, str | None]:
    """Normalize the useful-for line. Returns (body, error_code)."""
    try:
        body = normalize_context(raw)
    except NormalizeError as exc:
        if exc.code == "too_long":
            return None, "too_long"
        raise
    if body and not config.allow_secrets() and looks_like_secret(body):
        return None, "secret_blocked"
    return body, None


@app.post("/v1/sources/{source_id}/context")
def api_context(
    source_id: str,
    payload: ContextIn,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    require_auth(request, authorization)
    if source_detail(conn, source_id) is None:
        raise HTTPException(status_code=404, detail=_problem("not_found", "source missing", 404))
    body, err = _prepare_context(payload.body)
    if err:
        raise HTTPException(status_code=400, detail=_problem(err, err, 400))
    upsert_context(conn, source_id, body or "")
    return Response(status_code=204)


@app.post("/v1/sources/{source_id}/context-form")
def context_form(
    source_id: str,
    request: Request,
    body: Annotated[str, Form()] = "",
    q: Annotated[str, Form()] = "",
    conn: sqlite3.Connection = Depends(get_conn),
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    if not is_authed(request, authorization):
        return RedirectResponse("/", status_code=302)
    if source_detail(conn, source_id) is None:
        return RedirectResponse("/", status_code=303)
    prepared, err = _prepare_context(body)
    if err:
        return _inbox_redirect(source_id, q, conn, error=err)
    upsert_context(conn, source_id, prepared or "")
    return _inbox_redirect(source_id, q, conn)


class ReuseIn(BaseModel):
    kind: str


@app.post("/v1/sources/{source_id}/reuse")
def api_reuse(
    source_id: str,
    payload: ReuseIn,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    require_auth(request, authorization)
    if payload.kind not in {"copy_source", "mark_used"}:
        raise HTTPException(status_code=400, detail=_problem("bad_reuse", "unknown reuse kind", 400))
    if source_detail(conn, source_id) is None:
        raise HTTPException(status_code=404, detail=_problem("not_found", "source missing", 404))
    mark_reuse(conn, source_id, payload.kind)
    return {"ok": True}


@app.post("/v1/captures/undo")
def api_undo(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    require_auth(request, authorization)
    result = undo_latest(conn)
    return {"ok": True, "result": result}


@app.delete("/v1/captures/{capture_id}")
def api_delete(
    capture_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    require_auth(request, authorization)
    result = delete_capture(conn, capture_id)
    if result == "missing":
        raise HTTPException(status_code=404, detail=_problem("not_found", "capture missing", 404))
    return {"ok": True, "result": result}


def _inbox_redirect(
    source_id: str,
    q: str,
    conn: sqlite3.Connection,
    *,
    error: str | None = None,
) -> RedirectResponse:
    """303 back to the inbox. Keep `q` only if this source still MATCHES it."""
    params: dict[str, str] = {"selected": source_id}
    if error:
        params["context_error"] = error
    if q and source_matches_query(conn, source_id, q):
        params["q"] = q
    return RedirectResponse("/?" + urlencode(params), status_code=303)


@app.get("/", response_class=HTMLResponse)
def inbox(
    request: Request,
    q: str = Query(default=""),
    selected: str | None = None,
    context_error: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
    authorization: Annotated[str | None, Header()] = None,
) -> HTMLResponse:
    if not is_authed(request, authorization):
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {"error": None, "t": t, "catalog": getattr(request.app.state, "catalog", {})},
        )
    if context_error not in {"too_long", "secret_blocked"}:
        context_error = None
    rows = recency_list(conn) if not q else search_sources(conn, q)
    catalog = request.app.state.catalog
    current = None
    if rows:
        wanted = selected or rows[0]["source_id"]
        current = source_detail(conn, wanted)
        if current is None and rows:
            current = source_detail(conn, rows[0]["source_id"])
    return TEMPLATES.TemplateResponse(
        request,
        "inbox.html",
        {
            "q": q,
            "selected": selected,
            "context_error": context_error,
            "rows": rows,
            "current": current,
            "t": t,
            "catalog": catalog,
            "display_chars": DISPLAY_CHARS,
        },
    )


@app.post("/v1/login")
def login(request: Request, token: Annotated[str, Form()] = "") -> Response:
    if not token_matches(token, config.token()):
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {"error": "auth", "t": t, "catalog": getattr(request.app.state, "catalog", {})},
            status_code=401,
        )
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(
        config.COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        path="/",
        secure=False,
    )
    return resp


@app.post("/v1/sources/{source_id}/reuse-form")
def reuse_form(
    source_id: str,
    request: Request,
    kind: Annotated[str, Form()] = "mark_used",
    conn: sqlite3.Connection = Depends(get_conn),
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    if not is_authed(request, authorization):
        return RedirectResponse("/", status_code=302)
    if kind in {"copy_source", "mark_used"} and source_detail(conn, source_id):
        mark_reuse(conn, source_id, kind)
    return RedirectResponse(f"/?selected={source_id}", status_code=302)


@app.post("/v1/captures/{capture_id}/delete-form")
def delete_form(
    capture_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    if not is_authed(request, authorization):
        return RedirectResponse("/", status_code=302)
    delete_capture(conn, capture_id)
    return RedirectResponse("/", status_code=302)
