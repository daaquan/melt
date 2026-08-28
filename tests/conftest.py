from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TOKEN = "test-token-abcdef"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "melt.db"
    monkeypatch.setenv("MELT_TOKEN", TOKEN)
    monkeypatch.setenv("MELT_DB_PATH", str(db))
    monkeypatch.setenv("MELT_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver")
    monkeypatch.delenv("MELT_ALLOW_SECRETS", raising=False)
    from melt.app import app

    with TestClient(app) as test_client:
        yield test_client


def auth_headers(key: str | None = "k1") -> dict[str, str]:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers
