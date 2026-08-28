from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from tests.conftest import TOKEN, auth_headers

PHASE1_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE sources (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  normalized_body TEXT NOT NULL,
  hash TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL
);

CREATE TABLE captures (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  captured_at INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  raw_body TEXT NOT NULL
);

CREATE TABLE digests (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  summary TEXT NOT NULL,
  useful_for_json TEXT NOT NULL,
  retrieval_phrases_json TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_id TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE reuse_events (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE VIRTUAL TABLE sources_fts USING fts5(
  source_id UNINDEXED,
  body,
  digest_text
);
"""

SECRET_LINE = "key ghp_abcdefghijklmnopqrstuvwxyz0123456789 extra"


def _capture(client, body: str, key: str | None = None) -> str:
    headers = auth_headers(key or str(uuid.uuid4()))
    r = client.post("/v1/captures", json={"kind": "text", "body": body}, headers=headers)
    assert r.status_code == 201
    return r.json()["source_id"]


def _post_context(client, source_id: str, body: str):
    return client.post(
        f"/v1/sources/{source_id}/context",
        json={"body": body},
        headers=auth_headers(None),
    )


def _db(client) -> sqlite3.Connection:
    from melt import config
    from melt.db import connect

    return connect(config.db_path())


def _fts_sql(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'sources_fts'"
    ).fetchone()
    return row[0] if row else ""


def _write_phase1(path: Path, phrases_json: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(PHASE1_SCHEMA)
    conn.execute("PRAGMA user_version = 0")
    conn.execute(
        "INSERT INTO sources VALUES ('s1', 'text', 'wal checkpoint under load', 'h1', 1)"
    )
    conn.execute(
        "INSERT INTO captures VALUES ('c1', 's1', 1, 'k1', 'wal checkpoint under load')"
    )
    conn.execute(
        """
        INSERT INTO digests VALUES (
          'd1', 's1', 'wal checkpoint under load', '[]', ?, 'stub', 'stub-v1', 'h1', 1
        )
        """,
        (phrases_json,),
    )
    conn.execute(
        """
        INSERT INTO sources_fts (source_id, body, digest_text)
        VALUES ('s1', 'wal checkpoint under load', 'wal checkpoint under load checkpoint')
        """
    )
    conn.commit()
    conn.close()


def test_post_context_get_and_fts(client) -> None:
    source_id = _capture(client, "clipboard noise only")
    r = _post_context(client, source_id, "sqlite wal for billing")
    assert r.status_code == 204
    detail = client.get(f"/v1/sources/{source_id}", headers=auth_headers(None))
    assert detail.json()["context"] == "sqlite wal for billing"
    hits = client.get(
        "/v1/search",
        params={"q": "sqlite wal for billing"},
        headers=auth_headers(None),
    )
    assert any(item["source_id"] == source_id for item in hits.json()["hits"])


def test_empty_context_deletes_row_and_fts(client) -> None:
    source_id = _capture(client, "keep the source words")
    assert _post_context(client, source_id, "unique-memo-token").status_code == 204
    assert _post_context(client, source_id, "  \n  ").status_code == 204
    detail = client.get(f"/v1/sources/{source_id}", headers=auth_headers(None))
    assert detail.json()["context"] is None
    conn = _db(client)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM contexts").fetchone()["n"] == 0
    finally:
        conn.close()
    misses = client.get(
        "/v1/search",
        params={"q": "unique-memo-token"},
        headers=auth_headers(None),
    )
    assert misses.json()["hits"] == []


def test_too_long_json_and_form(client) -> None:
    source_id = _capture(client, "length check source")
    assert _post_context(client, source_id, "a" * 200).status_code == 204
    over = client.post(
        f"/v1/sources/{source_id}/context",
        json={"body": "a" * 201},
        headers=auth_headers(None),
    )
    assert over.status_code == 400
    assert over.json()["code"] == "too_long"
    _post_context(client, source_id, "kept-short")
    client.cookies.set("melt_token", TOKEN)
    form = client.post(
        f"/v1/sources/{source_id}/context-form",
        data={"body": "b" * 201, "q": ""},
        follow_redirects=False,
    )
    assert form.status_code == 303
    qs = parse_qs(urlparse(form.headers["location"]).query)
    assert qs["context_error"] == ["too_long"]
    assert qs["selected"] == [source_id]
    detail = client.get(f"/v1/sources/{source_id}", headers=auth_headers(None))
    assert detail.json()["context"] == "kept-short"


def test_recapture_keeps_context_and_source_fts(client) -> None:
    source_id = _capture(client, "zephyr-source-token", "rec-a")
    assert _post_context(client, source_id, "memo-keep").status_code == 204
    again = client.post(
        "/v1/captures",
        json={"kind": "text", "body": "zephyr-source-token"},
        headers=auth_headers("rec-b"),
    )
    assert again.json()["source_id"] == source_id
    assert again.json()["occurrence_count"] == 2
    conn = _db(client)
    try:
        ctx = conn.execute("SELECT body FROM contexts WHERE source_id = ?", (source_id,)).fetchone()
        assert ctx["body"] == "memo-keep"
        assert conn.execute("SELECT COUNT(*) AS n FROM contexts").fetchone()["n"] == 1
    finally:
        conn.close()
    assert _post_context(client, source_id, "memo-after").status_code == 204
    hits = client.get(
        "/v1/search",
        params={"q": "zephyr-source-token"},
        headers=auth_headers(None),
    )
    assert any(item["source_id"] == source_id for item in hits.json()["hits"])


def test_undo_drops_context_and_fts(client) -> None:
    source_id = _capture(client, "gone with context")
    assert _post_context(client, source_id, "orphan-check").status_code == 204
    undo = client.post("/v1/captures/undo", headers=auth_headers(None))
    assert undo.status_code == 200
    missing = client.get(f"/v1/sources/{source_id}", headers=auth_headers(None))
    assert missing.status_code == 404
    conn = _db(client)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM contexts").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM sources_fts").fetchone()["n"] == 0
    finally:
        conn.close()


def test_inbox_shows_context_not_in_digest(client) -> None:
    source_id = _capture(client, "plain clipboard line")
    assert _post_context(client, source_id, "UNIQUE_MEMO_XYZ <script>alert(2)</script>").status_code == 204
    client.cookies.set("melt_token", TOKEN)
    page = client.get(f"/?selected={source_id}")
    assert page.status_code == 200
    assert "UNIQUE_MEMO_XYZ" in page.text
    assert "context-body" in page.text
    assert "<script>alert(2)</script>" not in page.text
    assert "Useful for" in page.text
    digest_at = page.text.index('class="pane digest"')
    assert "UNIQUE_MEMO_XYZ" not in page.text[digest_at:]
    assert "autofocus" not in page.text
    home = client.get("/")
    assert "autofocus" in home.text


def test_context_not_in_digest_json(client) -> None:
    source_id = _capture(client, "digest stays stub")
    assert _post_context(client, source_id, "user-voice-line").status_code == 204
    detail = client.get(f"/v1/sources/{source_id}", headers=auth_headers(None)).json()
    assert detail["context"] == "user-voice-line"
    assert "useful_for" not in detail["digest"]
    conn = _db(client)
    try:
        row = conn.execute(
            "SELECT useful_for_json FROM digests WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        assert json.loads(row["useful_for_json"]) == []
    finally:
        conn.close()


def test_migrate_phase1_file(tmp_path: Path) -> None:
    from melt.db import connect, init_db, search_sources

    path = tmp_path / "phase1.db"
    _write_phase1(path, '["checkpoint"]')
    init_db(path)
    conn = connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "user_text" in _fts_sql(conn)
        hits = search_sources(conn, "checkpoint")
        assert any(row["source_id"] == "s1" for row in hits)
    finally:
        conn.close()


def test_migrate_bad_phrases_leaves_old_fts(tmp_path: Path) -> None:
    from melt.db import init_db

    path = tmp_path / "bad.db"
    _write_phase1(path, "NOT JSON")
    with pytest.raises(json.JSONDecodeError):
        init_db(path)
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert "user_text" not in _fts_sql(conn)
    finally:
        conn.close()


def test_form_keeps_q_unless_cleared(client) -> None:
    source_id = _capture(client, "unrelated clipboard text xyz")
    assert _post_context(client, source_id, "sqlite wal for billing").status_code == 204
    client.cookies.set("melt_token", TOKEN)
    keep = client.post(
        f"/v1/sources/{source_id}/context-form",
        data={"body": "sqlite wal for billing", "q": "sqlite wal for billing"},
        follow_redirects=False,
    )
    assert keep.status_code == 303
    qs = parse_qs(urlparse(keep.headers["location"]).query)
    assert qs["selected"] == [source_id]
    assert qs["q"] == ["sqlite wal for billing"]
    assert "context_error" not in qs

    clear = client.post(
        f"/v1/sources/{source_id}/context-form",
        data={"body": "", "q": "sqlite wal for billing"},
        follow_redirects=False,
    )
    assert clear.status_code == 303
    qs2 = parse_qs(urlparse(clear.headers["location"]).query)
    assert qs2["selected"] == [source_id]
    assert "q" not in qs2
    page = client.get(clear.headers["location"])
    assert page.status_code == 200
    assert "unrelated clipboard text xyz" in page.text


def test_context_secret_blocked_and_allow(client, monkeypatch: pytest.MonkeyPatch) -> None:
    source_id = _capture(client, "ordinary clip")
    blocked = _post_context(client, source_id, SECRET_LINE)
    assert blocked.status_code == 400
    assert blocked.json()["code"] == "secret_blocked"
    client.cookies.set("melt_token", TOKEN)
    form = client.post(
        f"/v1/sources/{source_id}/context-form",
        data={"body": SECRET_LINE, "q": ""},
        follow_redirects=False,
    )
    assert form.status_code == 303
    assert parse_qs(urlparse(form.headers["location"]).query)["context_error"] == [
        "secret_blocked"
    ]
    monkeypatch.setenv("MELT_ALLOW_SECRETS", "1")
    allowed = _post_context(client, source_id, SECRET_LINE)
    assert allowed.status_code == 204
    detail = client.get(f"/v1/sources/{source_id}", headers=auth_headers(None))
    assert detail.json()["context"] == SECRET_LINE


def test_replace_context_one_fts_row(client) -> None:
    source_id = _capture(client, "replace-base")
    assert _post_context(client, source_id, "alpha-term-aaa").status_code == 204
    assert _post_context(client, source_id, "beta-term-bbb").status_code == 204
    miss = client.get("/v1/search", params={"q": "alpha-term-aaa"}, headers=auth_headers(None))
    assert miss.json()["hits"] == []
    hit = client.get("/v1/search", params={"q": "beta-term-bbb"}, headers=auth_headers(None))
    found = [item["source_id"] for item in hit.json()["hits"]]
    assert found == [source_id]
    conn = _db(client)
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM sources_fts WHERE source_id = ?",
            (source_id,),
        ).fetchone()["n"]
        assert n == 1
    finally:
        conn.close()


def test_undo_latest_no_deadlock_with_ingest(tmp_path: Path) -> None:
    from melt.db import connect, ingest, init_db, undo_latest
    from melt.normalize import normalize

    path = tmp_path / "race.db"
    init_db(path)
    errors: list[BaseException] = []

    def worker_ingest() -> None:
        conn = connect(path)
        try:
            for i in range(40):
                kind, body = normalize("text", f"payload {i} {uuid.uuid4()}")
                ingest(
                    conn,
                    kind=kind,
                    raw_body=body,
                    normalized_body=body,
                    idempotency_key=str(uuid.uuid4()),
                )
        except BaseException as exc:
            errors.append(exc)
        finally:
            conn.close()

    def worker_undo() -> None:
        conn = connect(path)
        try:
            for _ in range(40):
                undo_latest(conn)
        except BaseException as exc:
            errors.append(exc)
        finally:
            conn.close()

    threads = [
        threading.Thread(target=worker_ingest),
        threading.Thread(target=worker_undo),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []

    conn = connect(path)
    try:
        captures = conn.execute("SELECT COUNT(*) AS n FROM captures").fetchone()["n"]
        sources = conn.execute("SELECT COUNT(*) AS n FROM sources").fetchone()["n"]
        assert captures >= 0
        assert sources >= 0
    finally:
        conn.close()


def test_undo_deletes_latest_at_lock_time(tmp_path: Path) -> None:
    from melt.db import connect, ingest, init_db, undo_latest
    from melt.normalize import normalize

    path = tmp_path / "latest.db"
    init_db(path)
    conn = connect(path)
    try:
        first = ingest(
            conn,
            kind="text",
            raw_body="first-item",
            normalized_body=normalize("text", "first-item")[1],
            idempotency_key="k1",
        )
        second = ingest(
            conn,
            kind="text",
            raw_body="second-item",
            normalized_body=normalize("text", "second-item")[1],
            idempotency_key="k2",
        )
        assert undo_latest(conn) == "source"
        leftover = conn.execute("SELECT id FROM sources").fetchall()
        assert [row["id"] for row in leftover] == [first["source_id"]]
        gone = conn.execute(
            "SELECT id FROM captures WHERE id = ?", (second["capture_id"],)
        ).fetchone()
        assert gone is None
    finally:
        conn.close()
