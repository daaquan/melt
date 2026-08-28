from __future__ import annotations

import threading
import unicodedata
import uuid

from tests.conftest import TOKEN, auth_headers


def test_same_text_one_source_two_captures(client) -> None:
    a = client.post("/v1/captures", json={"kind": "text", "body": "hello melt"}, headers=auth_headers("a"))
    b = client.post("/v1/captures", json={"kind": "text", "body": "hello melt"}, headers=auth_headers("b"))
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["source_id"] == b.json()["source_id"]
    assert a.json()["capture_id"] != b.json()["capture_id"]
    assert b.json()["occurrence_count"] == 2
    assert a.json()["digest_status"] == "stub"


def test_url_slash_and_utm_merge_fragments_differ(client) -> None:
    u1 = "https://Example.com/?utm_source=x&b=2&a=1"
    u2 = "https://example.com?a=1&b=2"
    u3 = "https://example.com#frag"
    r1 = client.post("/v1/captures", json={"kind": "url", "body": u1}, headers=auth_headers("u1"))
    r2 = client.post("/v1/captures", json={"kind": "url", "body": u2}, headers=auth_headers("u2"))
    r3 = client.post("/v1/captures", json={"kind": "url", "body": u3}, headers=auth_headers("u3"))
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["source_id"] == r2.json()["source_id"]
    assert r3.json()["source_id"] != r1.json()["source_id"]
    p1 = client.post(
        "/v1/captures",
        json={"kind": "url", "body": "https://example.com/path/"},
        headers=auth_headers("p1"),
    )
    p2 = client.post(
        "/v1/captures",
        json={"kind": "url", "body": "https://example.com/path"},
        headers=auth_headers("p2"),
    )
    assert p1.json()["source_id"] != p2.json()["source_id"]


def test_ingest_one_stub_txn(client) -> None:
    r = client.post("/v1/captures", json={"kind": "text", "body": "only once"}, headers=auth_headers("t"))
    assert r.status_code == 201
    source_id = r.json()["source_id"]
    detail = client.get(f"/v1/sources/{source_id}", headers=auth_headers(None))
    assert detail.status_code == 200
    assert detail.json()["digest"]["model"] == "stub"
    recapture = client.post(
        "/v1/captures", json={"kind": "text", "body": "only once"}, headers=auth_headers("t2")
    )
    assert recapture.json()["occurrence_count"] == 2
    again = client.get(f"/v1/sources/{source_id}", headers=auth_headers(None))
    assert len(again.json()["captured_at"]) == 2


def test_idempotency_same_key_same_body(client) -> None:
    body = {"kind": "text", "body": "idem"}
    a = client.post("/v1/captures", json=body, headers=auth_headers("same"))
    b = client.post("/v1/captures", json=body, headers=auth_headers("same"))
    assert a.json()["capture_id"] == b.json()["capture_id"]
    assert a.json()["occurrence_count"] == b.json()["occurrence_count"] == 1


def test_idempotency_same_key_different_body(client) -> None:
    client.post("/v1/captures", json={"kind": "text", "body": "one"}, headers=auth_headers("dup"))
    r = client.post("/v1/captures", json={"kind": "text", "body": "two"}, headers=auth_headers("dup"))
    assert r.status_code == 409


def test_missing_idempotency_still_201(client) -> None:
    r = client.post(
        "/v1/captures",
        json={"kind": "text", "body": "no key"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 201


def test_nfc_same_source(client) -> None:
    nfd = unicodedata.normalize("NFD", "café")
    nfc = unicodedata.normalize("NFC", "café")
    a = client.post("/v1/captures", json={"kind": "text", "body": nfd}, headers=auth_headers("n1"))
    b = client.post("/v1/captures", json={"kind": "text", "body": nfc}, headers=auth_headers("n2"))
    assert a.json()["source_id"] == b.json()["source_id"]


def test_oversize_413(client) -> None:
    body = "x" * (1_048_576 + 1)
    r = client.post("/v1/captures", json={"kind": "text", "body": body}, headers=auth_headers("big"))
    assert r.status_code == 413


def test_exact_1mib_201(client) -> None:
    body = "x" * 1_048_576
    r = client.post("/v1/captures", json={"kind": "text", "body": body}, headers=auth_headers("okbig"))
    assert r.status_code == 201


def test_secret_blocked(client) -> None:
    r = client.post(
        "/v1/captures",
        json={"kind": "text", "body": "key ghp_abcdefghijklmnopqrstuvwxyz0123456789 extra"},
        headers=auth_headers("sec"),
    )
    assert r.status_code == 400


def test_content_length_gate(client) -> None:
    r = client.post(
        "/v1/captures",
        content=b"x",
        headers={
            **auth_headers("cl"),
            "Content-Length": str(2_000_000),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 413


def test_concurrent_same_payload(client) -> None:
    errors: list[int] = []
    ids: list[str] = []

    def worker(i: int) -> None:
        r = client.post(
            "/v1/captures",
            json={"kind": "text", "body": "race"},
            headers=auth_headers(f"race-{i}-{uuid.uuid4()}"),
        )
        errors.append(r.status_code)
        if r.status_code == 201:
            ids.append(r.json()["source_id"])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == [201, 201]
    assert len(set(ids)) == 1
