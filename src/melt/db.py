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

CREATE TABLE IF NOT EXISTS contexts (
  source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
  body TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS sources_fts USING fts5(
  source_id UNINDEXED,
  body,
  digest_text,
  user_text
);
"""


# journal_mode persists in the database file. These two are per connection.
PRAGMAS = (
    "PRAGMA busy_timeout=30000",
    "PRAGMA foreign_keys=ON",
)

_LIST_SELECT = """
        SELECT s.id AS source_id, s.kind, s.normalized_body,
               c.raw_body, c.captured_at, c.id AS capture_id,
               (SELECT COUNT(*) FROM captures cx WHERE cx.source_id = s.id) AS occ,
               d.summary, d.model, d.retrieval_phrases_json, d.useful_for_json,
               ctx.body AS context_body
        FROM {from_clause}
        JOIN captures c ON c.id = (
          SELECT id FROM captures WHERE source_id = s.id
          ORDER BY captured_at DESC, id DESC LIMIT 1
        )
        LEFT JOIN digests d ON d.id = (
          SELECT id FROM digests WHERE source_id = s.id
          ORDER BY created_at DESC, id DESC LIMIT 1
        )
        LEFT JOIN contexts ctx ON ctx.source_id = s.id
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection. Assumes init_db has already created the schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        path, check_same_thread=False, isolation_level=None, timeout=30
    )
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    return conn


def init_db(path: Path) -> None:
    """Create the schema and migrate FTS. Call this once at startup."""
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        migrate_db(conn)
    finally:
        conn.close()


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id() -> str:
    return str(uuid.uuid4())


_INGEST_LOCK = threading.Lock()


class HashConflict(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _join_digest(summary: str, phrases: list[str]) -> str:
    return " ".join([summary, *phrases])


def digest_text_for(conn: sqlite3.Connection, source_id: str) -> str:
    digest = latest_digest(conn, source_id)
    if digest is None:
        return ""
    phrases = json.loads(digest["retrieval_phrases_json"])
    return _join_digest(digest["summary"], phrases)


def _rebuild_fts_row(conn: sqlite3.Connection, source_id: str) -> None:
    """Replace the FTS row from sources + latest digest + context. Caller holds lock+txn."""
    source = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if source is None:
        conn.execute("DELETE FROM sources_fts WHERE source_id = ?", (source_id,))
        return
    ctx = conn.execute(
        "SELECT body FROM contexts WHERE source_id = ?", (source_id,)
    ).fetchone()
    user_text = ctx["body"] if ctx else ""
    conn.execute("DELETE FROM sources_fts WHERE source_id = ?", (source_id,))
    conn.execute(
        """
        INSERT INTO sources_fts (source_id, body, digest_text, user_text)
        VALUES (?, ?, ?, ?)
        """,
        (
            source_id,
            source["normalized_body"],
            digest_text_for(conn, source_id),
            user_text,
        ),
    )


def migrate_db(conn: sqlite3.Connection) -> None:
    """Rebuild 4-col FTS. Parse phrases before DROP so a bad file stays at version 0."""
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= 1:
        return

    rows = conn.execute(
        """
        SELECT s.id AS source_id, s.normalized_body,
               d.summary, d.retrieval_phrases_json
        FROM sources s
        LEFT JOIN digests d ON d.id = (
          SELECT id FROM digests WHERE source_id = s.id
          ORDER BY created_at DESC, id DESC LIMIT 1
        )
        """
    ).fetchall()

    rebuilt: list[tuple[str, str, str]] = []
    for row in rows:
        phrases_json = row["retrieval_phrases_json"]
        if phrases_json is None:
            digest_text = ""
        else:
            phrases = json.loads(phrases_json)
            digest_text = _join_digest(row["summary"], phrases)
        rebuilt.append((row["source_id"], row["normalized_body"], digest_text))

    ctx_map: dict[str, str] = {}
    if _table_exists(conn, "contexts"):
        for ctx in conn.execute("SELECT source_id, body FROM contexts"):
            ctx_map[ctx["source_id"]] = ctx["body"]

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contexts (
              source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
              body TEXT NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("DROP TABLE IF EXISTS sources_fts")
        conn.execute(
            """
            CREATE VIRTUAL TABLE sources_fts USING fts5(
              source_id UNINDEXED,
              body,
              digest_text,
              user_text
            )
            """
        )
        for source_id, body, digest_text in rebuilt:
            conn.execute(
                """
                INSERT INTO sources_fts (source_id, body, digest_text, user_text)
                VALUES (?, ?, ?, ?)
                """,
                (source_id, body, digest_text, ctx_map.get(source_id, "")),
            )
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


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
                    """
                    INSERT INTO sources_fts (source_id, body, digest_text, user_text)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        normalized_body,
                        _join_digest(summary, phrases),
                        "",
                    ),
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
    sql = _LIST_SELECT.format(from_clause="sources s") + """
        ORDER BY c.captured_at DESC, c.id DESC
        LIMIT ?
        """
    return conn.execute(sql, (limit,)).fetchall()


def search_sources(conn: sqlite3.Connection, q: str) -> list[sqlite3.Row]:
    match = fts_query(q)
    if match is None:
        return []
    sql = _LIST_SELECT.format(from_clause="sources_fts JOIN sources s ON s.id = sources_fts.source_id")
    sql += """
        WHERE sources_fts MATCH ?
        ORDER BY rank
        """
    return conn.execute(sql, (match,)).fetchall()


def source_matches_query(conn: sqlite3.Connection, source_id: str, q: str) -> bool:
    match = fts_query(q)
    if match is None:
        return False
    row = conn.execute(
        """
        SELECT 1 FROM sources_fts
        WHERE sources_fts MATCH ? AND source_id = ?
        """,
        (match, source_id),
    ).fetchone()
    return row is not None


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
    ctx = conn.execute(
        "SELECT body FROM contexts WHERE source_id = ?", (source_id,)
    ).fetchone()
    return {
        "source": source,
        "captures": captures,
        "digest": digest,
        "used_count": int(used),
        "context": ctx["body"] if ctx else None,
    }


def mark_reuse(conn: sqlite3.Connection, source_id: str, kind: str) -> None:
    conn.execute(
        "INSERT INTO reuse_events (id, source_id, kind, created_at) VALUES (?, ?, ?, ?)",
        (new_id(), source_id, kind, now_ms()),
    )
    conn.commit()


def upsert_context(conn: sqlite3.Connection, source_id: str, body: str) -> str:
    """Write or delete the useful-for line. `body` is already normalized.

    Empty body deletes the row. Rebuilds FTS from sources + latest digest, never
    from the old FTS row. Returns 'ok' or 'missing'.
    """
    with _INGEST_LOCK:
        conn.execute("BEGIN IMMEDIATE")
        try:
            source = conn.execute(
                "SELECT id FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
            if source is None:
                conn.rollback()
                return "missing"
            if not body:
                conn.execute("DELETE FROM contexts WHERE source_id = ?", (source_id,))
            else:
                conn.execute(
                    """
                    INSERT INTO contexts (source_id, body, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(source_id) DO UPDATE SET
                      body = excluded.body,
                      updated_at = excluded.updated_at
                    """,
                    (source_id, body, now_ms()),
                )
            _rebuild_fts_row(conn, source_id)
            conn.commit()
            return "ok"
        except Exception:
            conn.rollback()
            raise


def _delete_under_lock(conn: sqlite3.Connection, capture_id: str | None) -> str:
    """Caller holds `_INGEST_LOCK`. None means the latest capture at lock time."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        if capture_id is None:
            row = conn.execute(
                """
                SELECT id FROM captures
                ORDER BY captured_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.rollback()
                return "empty"
            capture_id = row["id"]
        row = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
        if row is None:
            conn.rollback()
            return "missing"
        source_id = row["source_id"]
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


def delete_capture(conn: sqlite3.Connection, capture_id: str) -> str:
    with _INGEST_LOCK:
        return _delete_under_lock(conn, capture_id)


def undo_latest(conn: sqlite3.Connection) -> str:
    # Do not `with _INGEST_LOCK` here then call delete_capture: the lock is
    # non-reentrant. Latest is selected inside the same locked helper.
    with _INGEST_LOCK:
        return _delete_under_lock(conn, None)
