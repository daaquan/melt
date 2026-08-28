from __future__ import annotations

from tests.conftest import TOKEN, auth_headers


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
    assert "inbox" not in r.text.lower() or "token" in r.text.lower()


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
