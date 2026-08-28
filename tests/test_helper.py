from __future__ import annotations

import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def load_helper() -> ModuleType:
    path = str(ROOT / "scripts" / "melt-capture")
    loader = SourceFileLoader("melt_capture_under_test", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_locale_keys_exist() -> None:
    en = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    ja = json.loads((ROOT / "locales" / "ja.json").read_text(encoding="utf-8"))
    for key in ("toast.saved", "toast.saved_nth", "toast.failed", "list.empty"):
        assert key in en
        assert key in ja
    assert "Already seen" not in en.values()
    assert "Already seen" not in en


def test_dead_letter_400_continues(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MELT_STATE_DIR", str(tmp_path))
    helper = load_helper()
    statuses = [400, 201]

    def fake_post(api, token, kind, body, key):
        status = statuses.pop(0)
        return status, {"capture_id": "x", "occurrence_count": 1}

    helper.post_capture = fake_post
    helper.append_jsonl(
        helper.failed_file(),
        {"ts": 1, "kind": "text", "body": "bad", "idempotency_key": "k-bad", "error": 400},
    )
    helper.append_jsonl(
        helper.failed_file(),
        {"ts": 2, "kind": "text", "body": "ok", "idempotency_key": "k-ok", "error": 500},
    )
    catalog = {"toast.saved": "Saved", "toast.saved_nth": "Saved · {n}th time"}
    ok = helper.replay_queue(catalog, "http://x", "t", True)
    assert ok is True
    assert helper.dead_file().is_file()
    leftover = helper.load_failed()
    assert leftover == []


def test_replay_401_skips_live(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MELT_STATE_DIR", str(tmp_path))
    helper = load_helper()

    def fake_post(*args, **kwargs):
        return 401, {}

    helper.post_capture = fake_post
    helper.append_jsonl(
        helper.failed_file(),
        {"ts": 1, "kind": "text", "body": "keep", "idempotency_key": "k1", "error": 401},
    )
    ok = helper.replay_queue({}, "http://x", "t", True)
    assert ok is False
    leftover = helper.load_failed()
    assert leftover[0]["idempotency_key"] == "k1"


def test_helper_resolves_saved_keys() -> None:
    helper = load_helper()
    catalog = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    assert helper.t(catalog, "toast.saved") == "Saved"
    assert "3" in helper.t(catalog, "toast.saved_nth", n=3)
