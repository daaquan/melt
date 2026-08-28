from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from melt.normalize import fts_query, source_hash, stub_phrases

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=30000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  normalized_body TEXT NOT NULL,
  hash TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS captures (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  captured_at INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  raw_body TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS digests (
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

CREATE TABLE IF NOT EXISTS reuse_events (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS sources_fts USING fts5(
  source_id UNINDEXED,
  body,
  digest_text
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        path, check_same_thread=False, isolation_level=None, timeout=30
    )
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id() -> str:
    return str(uuid.uuid4())


_INGEST_LOCK = threading.Lock()


class HashConflict(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


def get_capture_by_key(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM captures WHERE idempotency_key = ?", (key,)
    ).fetchone()


def occurrence_count(conn: sqlite3.Connection, source_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM captures WHERE source_id = ?", (source_id,)
    ).fetchone()
    return int(row["n"])


def latest_digest(conn: sqlite3.Connection, source_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM digests
        WHERE source_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (source_id,),
    ).fetchone()


def ingest(
    conn: sqlite3.Connection,
    *,
    kind: str,
    raw_body: str,
    normalized_body: str,
    idempotency_key: str,
) -> dict:
    existing = get_capture_by_key(conn, idempotency_key)
    if existing is not None:
        if existing["raw_body"] != raw_body:
            raise IdempotencyConflict
        source = conn.execute(
            "SELECT * FROM sources WHERE id = ?", (existing["source_id"],)
        ).fetchone()
        digest = latest_digest(conn, existing["source_id"])
        return {
            "capture_id": existing["id"],
            "source_id": existing["source_id"],
            "occurrence_count": occurrence_count(conn, existing["source_id"]),
            "digest_status": digest["model"] if digest else "stub",
            "created": False,
        }

    digest_input = raw_body if kind == "text" else normalized_body
    digest_hash = source_hash(kind, normalized_body)
    phrases = stub_phrases(digest_input)
    summary = digest_input[:240]
    captured_at = now_ms()
    capture_id = new_id()

    with _INGEST_LOCK:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM sources WHERE hash = ?", (digest_hash,)
            ).fetchone()
            if row is not None:
                if row["kind"] != kind or row["normalized_body"] != normalized_body:
                    raise HashConflict
                source_id = row["id"]
                conn.execute(
                    """
                    INSERT INTO captures (id, source_id, captured_at, idempotency_key, raw_body)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (capture_id, source_id, captured_at, idempotency_key, raw_body),
                )
                digest = latest_digest(conn, source_id)
            else:
                source_id = new_id()
                conn.execute(
                    """
                    INSERT INTO sources (id, kind, normalized_body, hash, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (source_id, kind, normalized_body, digest_hash, captured_at),
                )
                conn.execute(
                    """
                    INSERT INTO captures (id, source_id, captured_at, idempotency_key, raw_body)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (capture_id, source_id, captured_at, idempotency_key, raw_body),
                )
                digest_id = new_id()
                conn.execute(
                    """
                    INSERT INTO digests (
                      id, source_id, summary, useful_for_json, retrieval_phrases_json,
                      model, prompt_id, source_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'stub', 'stub-v1', ?, ?)
                    """,
                    (
                        digest_id,
                        source_id,
                        summary,
                        "[]",
                        json.dumps(phrases),
                        digest_hash,
                        captured_at,
                    ),
                )
                conn.execute(
                    "INSERT INTO sources_fts (source_id, body, digest_text) VALUES (?, ?, ?)",
                    (source_id, normalized_body, " ".join([summary, *phrases])),
                )
                digest = conn.execute(
                    "SELECT * FROM digests WHERE id = ?", (digest_id,)
                ).fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "capture_id": capture_id,
        "source_id": source_id,
        "occurrence_count": occurrence_count(conn, source_id),
        "digest_status": digest["model"] if digest else "stub",
        "created": True,
    }


def recency_list(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT s.id AS source_id, s.kind, s.normalized_body,
               c.raw_body, c.captured_at, c.id AS capture_id,
               (SELECT COUNT(*) FROM captures cx WHERE cx.source_id = s.id) AS occ,
               d.summary, d.model, d.retrieval_phrases_json, d.useful_for_json
        FROM sources s
        JOIN captures c ON c.id = (
          SELECT id FROM captures WHERE source_id = s.id
          ORDER BY captured_at DESC, id DESC LIMIT 1
        )
        LEFT JOIN digests d ON d.id = (
          SELECT id FROM digests WHERE source_id = s.id
          ORDER BY created_at DESC, id DESC LIMIT 1
        )
        ORDER BY c.captured_at DESC, c.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def search_sources(conn: sqlite3.Connection, q: str) -> list[sqlite3.Row]:
    match = fts_query(q)
    if match is None:
        return []
    return conn.execute(
        """
        SELECT s.id AS source_id, s.kind, s.normalized_body,
               c.raw_body, c.captured_at, c.id AS capture_id,
               (SELECT COUNT(*) FROM captures cx WHERE cx.source_id = s.id) AS occ,
               d.summary, d.model, d.retrieval_phrases_json, d.useful_for_json
        FROM sources_fts
        JOIN sources s ON s.id = sources_fts.source_id
        JOIN captures c ON c.id = (
          SELECT id FROM captures WHERE source_id = s.id
          ORDER BY captured_at DESC, id DESC LIMIT 1
        )
        LEFT JOIN digests d ON d.id = (
          SELECT id FROM digests WHERE source_id = s.id
          ORDER BY created_at DESC, id DESC LIMIT 1
        )
        WHERE sources_fts MATCH ?
        ORDER BY rank
        """,
        (match,),
    ).fetchall()


def source_detail(conn: sqlite3.Connection, source_id: str) -> dict | None:
    source = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if source is None:
        return None
    captures = conn.execute(
        """
        SELECT * FROM captures WHERE source_id = ?
        ORDER BY captured_at DESC, id DESC
        """,
        (source_id,),
    ).fetchall()
    digest = latest_digest(conn, source_id)
    used = conn.execute(
        "SELECT COUNT(*) AS n FROM reuse_events WHERE source_id = ? AND kind = 'mark_used'",
        (source_id,),
    ).fetchone()["n"]
    return {
        "source": source,
        "captures": captures,
        "digest": digest,
        "used_count": int(used),
    }


def mark_reuse(conn: sqlite3.Connection, source_id: str, kind: str) -> None:
    conn.execute(
        "INSERT INTO reuse_events (id, source_id, kind, created_at) VALUES (?, ?, ?, ?)",
        (new_id(), source_id, kind, now_ms()),
    )
    conn.commit()


def delete_capture(conn: sqlite3.Connection, capture_id: str) -> str:
    row = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
    if row is None:
        return "missing"
    source_id = row["source_id"]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM captures WHERE id = ?", (capture_id,))
        remaining = occurrence_count(conn, source_id)
        if remaining == 0:
            conn.execute("DELETE FROM sources_fts WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            conn.commit()
            return "source"
        conn.commit()
        return "capture"
    except Exception:
        conn.rollback()
        raise


def undo_latest(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT id FROM captures ORDER BY captured_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return "empty"
    return delete_capture(conn, row["id"])
