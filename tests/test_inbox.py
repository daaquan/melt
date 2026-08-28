from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

from tests.conftest import TOKEN, auth_headers

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "locales" / "en.json").read_text(encoding="utf-8")
)


class AttrCollector(HTMLParser):
    """Collects one attribute off every tag so we can assert on parsed HTML."""

    def __init__(self, tag: str, attr: str) -> None:
        super().__init__()
        self.tag = tag
        self.attr = attr
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != self.tag:
            return
        for name, value in attrs:
            if name == self.attr and value is not None:
                self.values.append(value)


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


def test_xss_escaped(client) -> None:
    client.post(
        "/v1/captures",
        json={"kind": "text", "body": "<script>alert(1)</script>"},
        headers=auth_headers("xss"),
    )
    client.cookies.set("melt_token", TOKEN)
    page = client.get("/")
    assert page.status_code == 200
    assert "<script>alert(1)</script>" not in page.text
    assert "alert(1)" in page.text


def test_login_wrong_token(client) -> None:
    r = client.post("/v1/login", data={"token": "nope"})
    assert r.status_code == 401
    assert "melt_token" not in r.headers.get("set-cookie", "")
    assert CATALOG["login.error"] in r.text


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
    page = client.get("/")
    assert page.status_code == 200
    assert "usable item" in page.text
    source_id = client.get("/v1/search", params={"q": "usable"}, headers=auth_headers(None)).json()["hits"][0][
        "source_id"
    ]
    used = client.post(
        f"/v1/sources/{source_id}/reuse",
        json={"kind": "mark_used"},
        headers=auth_headers(None),
    )
    assert used.status_code == 200


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
    assert "default-src 'self'" in page.headers["content-security-policy"]
    # `default-src 'self'` drops inline blocks, so the page must not rely on them.
    assert "<style>" not in page.text
    assert "<script>" not in page.text
    for asset in ("/static/app.css", "/static/inbox.js"):
        assert client.get(asset).status_code == 200


def test_delete_form_carries_a_parseable_confirm(client) -> None:
    client.post("/v1/captures", json={"kind": "text", "body": "deletable"}, headers=auth_headers("d1"))
    client.cookies.set("melt_token", TOKEN)
    page = client.get("/")
    parser = AttrCollector("form", "data-confirm")
    parser.feed(page.text)
    # A quote-bearing string interpolated into an attribute truncates it.
    assert parser.values == [CATALOG["action.delete_confirm"]]
