from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

from tests.conftest import TOKEN, auth_headers

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "locales" / "en.json").read_text(encoding="utf-8")
)


class InlineCodeFinder(HTMLParser):
    """Records <style> blocks and <script> tags that carry no src.

    The CSP has no 'unsafe-inline', so either one would be dropped by the
    browser and the shell would never boot.
    """

    def __init__(self) -> None:
        super().__init__()
        self.inline: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "style":
            self.inline.append("style")
        if tag == "script" and not any(name == "src" for name, _ in attrs):
            self.inline.append("script")


def test_search_includes_source_and_times(client) -> None:
    r = client.post(
        "/v1/captures",
        json={"kind": "text", "body": "wal checkpoint under load"},
        headers=auth_headers("s1"),
    )
    source_id = r.json()["source_id"]
    hits = client.get("/v1/search", params={"q": "checkpoint"}, headers=auth_headers(None))
    assert hits.status_code == 200
    found = hits.json()["hits"]
    assert any(item["source_id"] == source_id and item["captured_at"] for item in found)


def test_empty_search_200(client) -> None:
    r = client.get("/v1/search", params={"q": ""}, headers=auth_headers(None))
    assert r.status_code == 200
    assert r.json()["hits"] == []


def test_fts_metachar_200(client) -> None:
    client.post("/v1/captures", json={"kind": "text", "body": "quoted stuff"}, headers=auth_headers("q1"))
    for q in ['"', "*", "AND"]:
        r = client.get("/v1/search", params={"q": q}, headers=auth_headers(None))
        assert r.status_code == 200


def test_shell_never_carries_capture_text(client) -> None:
    """The one page the server renders is a fixed file.

    Capture bodies now reach the browser as JSON and are put in the DOM as text
    nodes by the client, so there is no template left to escape them wrong: the
    shell is byte-identical whether or not a capture holds a script tag.
    """
    empty = client.get("/")
    client.post(
        "/v1/captures",
        json={"kind": "text", "body": "<script>alert(1)</script>"},
        headers=auth_headers("xss"),
    )
    client.cookies.set("melt_token", TOKEN)
    page = client.get("/")
    assert page.status_code == 200
    assert page.text == empty.text
    assert "alert(1)" not in page.text

    # The payload survives intact on the JSON surface, where it is data.
    rows = client.get("/v1/inbox", headers=auth_headers(None)).json()["rows"]
    assert any(row["title"] == "<script>alert(1)</script>" for row in rows)


def test_login_wrong_token(client) -> None:
    r = client.post("/v1/login", data={"token": "nope"})
    assert r.status_code == 401
    assert "melt_token" not in r.headers.get("set-cookie", "")
    # The client reads `code` and picks the catalog string itself.
    assert r.json()["code"] == "auth"


def test_login_cookie_is_not_secure_on_http(client) -> None:
    r = client.post("/v1/login", data={"token": TOKEN}, follow_redirects=False)
    cookie = r.headers.get("set-cookie", "").lower()
    assert "melt_token=" in cookie
    assert "secure" not in cookie
    assert "httponly" in cookie


def test_login_cookie_is_secure_behind_trusted_proxy(client, monkeypatch) -> None:
    monkeypatch.setenv("MELT_TRUST_PROXY", "1")
    r = client.post(
        "/v1/login",
        data={"token": TOKEN},
        headers={"X-Forwarded-Proto": "https"},
        follow_redirects=False,
    )
    cookie = r.headers.get("set-cookie", "").lower()
    assert "secure" in cookie
    assert r.headers.get("strict-transport-security")


def test_forwarded_proto_ignored_without_trust_proxy(client) -> None:
    r = client.post(
        "/v1/login",
        data={"token": TOKEN},
        headers={"X-Forwarded-Proto": "https"},
        follow_redirects=False,
    )
    cookie = r.headers.get("set-cookie", "").lower()
    assert "secure" not in cookie
    assert r.headers.get("strict-transport-security") is None


def test_login_non_ascii_token_is_401_not_500(client) -> None:
    # secrets.compare_digest rejects non-ASCII str, so a str compare 500s here.
    r = client.post("/v1/login", data={"token": "caf\u00e9-\u30c8\u30fc\u30af\u30f3"})
    assert r.status_code == 401


def test_bearer_non_ascii_token_is_401_not_500(client) -> None:
    # Headers arrive as latin-1 bytes, so a client can hand us a non-ASCII token.
    r = client.get(
        "/v1/search",
        params={"q": "x"},
        headers={b"Authorization": "Bearer caf\u00e9".encode("latin-1")},
    )
    assert r.status_code == 401


def test_inbox_recency_and_mark_used(client) -> None:
    client.post("/v1/captures", json={"kind": "text", "body": "usable item"}, headers=auth_headers("u1"))
    client.cookies.set("melt_token", TOKEN)
    page = client.get("/v1/inbox")
    assert page.status_code == 200
    rows = page.json()["rows"]
    assert rows[0]["title"] == "usable item"
    assert rows[0]["used_count"] == 0
    source_id = rows[0]["source_id"]
    used = client.post(
        f"/v1/sources/{source_id}/reuse",
        json={"kind": "mark_used"},
        headers=auth_headers(None),
    )
    assert used.status_code == 200
    # The list carries the marker, so a used capture reads as used without
    # opening it.
    assert client.get("/v1/inbox").json()["rows"][0]["used_count"] == 1


def test_undo_last_deletes_source(client) -> None:
    r = client.post("/v1/captures", json={"kind": "text", "body": "gone"}, headers=auth_headers("g1"))
    source_id = r.json()["source_id"]
    undo = client.post("/v1/captures/undo", headers=auth_headers(None))
    assert undo.status_code == 200
    missing = client.get(f"/v1/sources/{source_id}", headers=auth_headers(None))
    assert missing.status_code == 404


def test_error_body_is_a_flat_problem(client) -> None:
    client.post("/v1/captures", json={"kind": "text", "body": "one"}, headers=auth_headers("shape"))
    conflict = client.post(
        "/v1/captures", json={"kind": "text", "body": "two"}, headers=auth_headers("shape")
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "conflict_idempotency"

    oversize = client.post(
        "/v1/captures",
        content=b"x",
        headers={
            **auth_headers("shape2"),
            "Content-Length": str(2_000_000),
            "Content-Type": "application/json",
        },
    )
    assert oversize.status_code == 413
    # Middleware and routes must agree, so `code` is readable off the top level.
    assert oversize.json()["code"] == "too_large"


def test_page_assets_survive_the_csp(client) -> None:
    client.post("/v1/captures", json={"kind": "text", "body": "styled"}, headers=auth_headers("css"))
    client.cookies.set("melt_token", TOKEN)
    page = client.get("/")
    csp = page.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    # Compiling the client's module needs this and nothing wider; plain eval()
    # stays blocked.
    assert "script-src 'self' 'wasm-unsafe-eval'" in csp
    assert "unsafe-inline" not in csp

    parser = InlineCodeFinder()
    parser.feed(page.text)
    assert parser.inline == []

    for asset in (
        "/static/app.css",
        "/static/icon.svg",
        "/static/ui/boot.js",
        "/static/ui/theme-boot.js",
        "/static/ui/melt.js",
        "/static/ui/melt_bg.wasm",
    ):
        assert client.get(asset).status_code == 200, asset

    # instantiateStreaming refuses anything but application/wasm, and
    # nosniff means the browser will not guess.
    wasm = client.get("/static/ui/melt_bg.wasm")
    assert wasm.headers["content-type"] == "application/wasm"


def test_catalog_reaches_the_client_intact(client) -> None:
    """Locale strings ride JSON now, not HTML attributes.

    The delete confirmation is the string that used to break: it carries
    quotes, and interpolating it into an attribute truncated it. Over
    /v1/i18n it arrives byte for byte.
    """
    catalog = client.get("/v1/i18n").json()["catalog"]
    assert catalog["action.delete_confirm"] == CATALOG["action.delete_confirm"]
    assert catalog == CATALOG
