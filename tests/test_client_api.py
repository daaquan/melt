"""The JSON surface the Dioxus client runs on.

The inbox is no longer server-rendered, so these routes are the contract: if
they hold, the WASM client has everything it needs, and a script has the same.
"""

from __future__ import annotations

import json
from pathlib import Path

from melt.app import DISPLAY_CHARS

from tests.conftest import TOKEN, auth_headers

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "locales" / "en.json").read_text(encoding="utf-8")
)


def _capture(client, body: str, key: str) -> str:
    r = client.post("/v1/captures", json={"kind": "text", "body": body}, headers=auth_headers(key))
    assert r.status_code == 201
    return r.json()["source_id"]


def test_shell_is_a_static_file(client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    # A cached shell could point at a bundle a rebuild has already replaced.
    assert page.headers["cache-control"] == "no-store"
    assert '<div id="main">' in page.text
    assert "/static/ui/boot.js" in page.text


def test_i18n_needs_no_session(client) -> None:
    # The token gate has to render before there is a cookie to render it with.
    r = client.get("/v1/i18n")
    assert r.status_code == 200
    assert r.json()["catalog"] == CATALOG


def test_session_probe_tracks_the_cookie(client) -> None:
    assert client.get("/v1/session").json() == {"authenticated": False}
    login = client.post("/v1/login", data={"token": TOKEN}, follow_redirects=False)
    assert login.status_code == 302
    assert client.get("/v1/session").json() == {"authenticated": True}
    # A bearer token works for the same probe, so a script can check it too.
    client.cookies.clear()
    assert client.get("/v1/session", headers=auth_headers(None)).json()["authenticated"] is True


def test_logout_clears_the_cookie(client) -> None:
    client.post("/v1/login", data={"token": TOKEN}, follow_redirects=False)
    assert client.get("/v1/session").json()["authenticated"] is True
    out = client.post("/v1/logout")
    assert out.status_code == 204
    assert client.get("/v1/session").json()["authenticated"] is False


def test_inbox_requires_auth(client) -> None:
    r = client.get("/v1/inbox")
    assert r.status_code == 401
    assert r.json()["code"] == "auth"


def test_inbox_is_recency_ordered_with_the_columns_the_list_paints(client) -> None:
    first = _capture(client, "older capture line", "i1")
    second = _capture(client, "newer capture line", "i2")
    rows = client.get("/v1/inbox", headers=auth_headers(None)).json()["rows"]
    assert [row["source_id"] for row in rows] == [second, first]
    row = rows[0]
    assert set(row) == {
        "source_id",
        "kind",
        "title",
        "captured_at",
        "occurrence_count",
        "used_count",
        "context",
    }
    assert row["title"] == "newer capture line"
    assert row["kind"] == "text"
    assert row["occurrence_count"] == 1
    assert row["context"] is None
    assert isinstance(row["captured_at"], int)


def test_inbox_title_is_the_first_line_only(client) -> None:
    _capture(client, "headline stays short\nand the rest is hidden", "t1")
    rows = client.get("/v1/inbox", headers=auth_headers(None)).json()["rows"]
    assert rows[0]["title"] == "headline stays short"


def test_inbox_title_is_capped(client) -> None:
    _capture(client, "x" * 500, "t2")
    rows = client.get("/v1/inbox", headers=auth_headers(None)).json()["rows"]
    assert len(rows[0]["title"]) == 80


def test_inbox_counts_recaptures(client) -> None:
    _capture(client, "copied twice", "r1")
    client.post("/v1/captures", json={"kind": "text", "body": "copied twice"}, headers=auth_headers("r2"))
    rows = client.get("/v1/inbox", headers=auth_headers(None)).json()["rows"]
    assert rows[0]["occurrence_count"] == 2


def test_inbox_searches_when_q_is_set(client) -> None:
    wanted = _capture(client, "wal checkpoint under load", "s1")
    _capture(client, "totally unrelated text", "s2")
    rows = client.get("/v1/inbox", params={"q": "checkpoint"}, headers=auth_headers(None)).json()["rows"]
    assert [row["source_id"] for row in rows] == [wanted]


def test_inbox_survives_fts_metacharacters(client) -> None:
    _capture(client, "quoted stuff", "m1")
    for q in ('"', "*", "AND", "NEAR(", "^"):
        r = client.get("/v1/inbox", params={"q": q}, headers=auth_headers(None))
        assert r.status_code == 200, q
        assert isinstance(r.json()["rows"], list)


def test_empty_inbox_is_an_empty_list(client) -> None:
    assert client.get("/v1/inbox", headers=auth_headers(None)).json()["rows"] == []


def test_preview_truncates_but_the_plain_read_does_not(client) -> None:
    """Selecting a capture must not drag a 1 MiB body across the wire.

    The client renders the preview and asks again, without it, only when the
    body is about to go on the clipboard — so the clipboard never gets a
    truncated source.
    """
    body = "y" * (DISPLAY_CHARS + 500)
    source_id = _capture(client, body, "p1")

    preview = client.get(f"/v1/sources/{source_id}", params={"preview": 1}, headers=auth_headers(None)).json()
    assert preview["truncated"] is True
    assert len(preview["raw_body"]) == DISPLAY_CHARS
    assert preview["raw_chars"] == len(body)

    full = client.get(f"/v1/sources/{source_id}", headers=auth_headers(None)).json()
    assert full["truncated"] is False
    assert full["raw_body"] == body
    assert full["raw_chars"] == len(body)


def test_preview_leaves_a_short_body_alone(client) -> None:
    source_id = _capture(client, "short enough", "p2")
    detail = client.get(f"/v1/sources/{source_id}", params={"preview": 1}, headers=auth_headers(None)).json()
    assert detail["truncated"] is False
    assert detail["raw_body"] == "short enough"


def test_source_detail_carries_what_the_actions_need(client) -> None:
    source_id = _capture(client, "actionable", "a1")
    again = client.post(
        "/v1/captures", json={"kind": "text", "body": "actionable"}, headers=auth_headers("a2")
    )
    assert again.json()["occurrence_count"] == 2
    client.post(f"/v1/sources/{source_id}/reuse", json={"kind": "mark_used"}, headers=auth_headers(None))

    detail = client.get(f"/v1/sources/{source_id}", headers=auth_headers(None)).json()
    assert detail["occurrence_count"] == 2
    assert detail["used_count"] == 1
    # Delete acts on a capture, not a source, so the id has to come with it.
    assert detail["latest_capture_id"] == again.json()["capture_id"]

    gone = client.delete(f"/v1/captures/{detail['latest_capture_id']}", headers=auth_headers(None))
    assert gone.status_code == 200
    left = client.get(f"/v1/sources/{source_id}", headers=auth_headers(None)).json()
    assert left["occurrence_count"] == 1
    assert left["latest_capture_id"] != detail["latest_capture_id"]


def test_missing_source_is_a_problem_object(client) -> None:
    r = client.get("/v1/sources/does-not-exist", headers=auth_headers(None))
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_every_error_code_the_client_shows_has_a_catalog_line(client) -> None:
    """The client renders `error.<code>.body` straight from the catalog.

    A code with no line would surface the key itself in the UI, so the two
    have to stay in step.
    """
    reachable = (
        "auth",             # cookie stopped matching MELT_TOKEN
        "not_found",        # the open capture was deleted elsewhere
        "too_long",         # useful-for over 200 characters
        "secret_blocked",   # useful-for looks like a token
        "too_large",        # size middleware
        "disk_full",        # sqlite could not write
        "api_unreachable",  # the fetch never landed
        "unknown",          # any code the catalog does not name
    )
    for code in reachable:
        assert f"error.{code}.body" in CATALOG, code


def test_every_static_file_is_served(client) -> None:
    """The shell pulls in a file tree, not a single script.

    wasm-bindgen emits loader snippets under nested directories, and a browser
    asks for them by the exact path baked into melt.js.
    """
    root = Path(__file__).resolve().parents[1] / "src" / "melt" / "static"
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert files, "static/ is empty; run scripts/build-ui.sh"
    for name in files:
        assert client.get(f"/static/{name}").status_code == 200, name


def test_package_data_covers_every_static_file() -> None:
    """The wheel has to carry all of it, not just the top level.

    `pip install -e .` reads straight off the working tree, so a package-data
    glob that misses a file is invisible until someone installs the wheel and
    the client 404s on a snippet. Mirror what setuptools does with the
    patterns and compare against the tree.
    """
    import glob as globlib
    import tomllib

    repo = Path(__file__).resolve().parents[1]
    config = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["melt"]

    package = repo / "src" / "melt"
    packaged = {
        Path(hit).resolve()
        for pattern in patterns
        for hit in globlib.glob(str(package / pattern), recursive=True)
        if Path(hit).is_file()
    }
    on_disk = {p.resolve() for p in (package / "static").rglob("*") if p.is_file()}
    missing = sorted(str(p.relative_to(package)) for p in on_disk - packaged)
    assert missing == [], f"not covered by package-data: {missing}"
