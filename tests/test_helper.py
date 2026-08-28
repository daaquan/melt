from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
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
    for key in ("toast.saved", "toast.saved_nth", "toast.saved_batch", "toast.failed", "list.empty"):
        assert key in en
        assert key in ja
    assert "Already seen" not in en.values()


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


def test_live_auth_failure_keeps_the_body(tmp_path, monkeypatch) -> None:
    """An auth failure must not discard the capture.

    Fix MELT_TOKEN, press the hotkey again, and the queued row replays.
    """
    monkeypatch.setenv("MELT_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("MELT_LOCALE_DIR", str(ROOT / "locales"))
    helper = load_helper()
    monkeypatch.setattr(helper.sys, "stdin", io.StringIO("worth keeping"))
    helper.post_capture = lambda *args, **kwargs: (401, {})

    assert helper.main(["--stdin", "--no-notify"]) == 1

    queued = helper.load_failed()
    assert [row["body"] for row in queued] == ["worth keeping"]


def test_packaged_helper_loads_parent_env(tmp_path, monkeypatch) -> None:
    helper = load_helper()
    dist = tmp_path / "dist"
    dist.mkdir()
    executable = dist / "melt-capture.exe"
    executable.touch()
    (tmp_path / ".env").write_text(
        "# shared with compose\n"
        "MELT_TOKEN=from-env-file\n"
        "MELT_DB_PATH=/data/melt.db\n"
        "OTHER_VALUE=ignored\n",
        encoding="utf-8",
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(helper.sys, "frozen", True, raising=False)
    monkeypatch.setattr(helper.sys, "executable", str(executable))
    monkeypatch.delenv("MELT_ENV_FILE", raising=False)
    monkeypatch.delenv("MELT_TOKEN", raising=False)
    monkeypatch.delenv("MELT_DB_PATH", raising=False)
    monkeypatch.delenv("OTHER_VALUE", raising=False)

    assert helper.load_environment() == tmp_path / ".env"
    assert os.environ["MELT_TOKEN"] == "from-env-file"
    assert "OTHER_VALUE" not in os.environ
    assert "MELT_DB_PATH" not in os.environ


def test_helper_reads_env_from_working_directory(tmp_path, monkeypatch) -> None:
    """A desktop shortcut passes settings by starting in the repo, not by exporting."""
    helper = load_helper()
    (tmp_path / ".env").write_text("MELT_TOKEN=from-working-dir\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MELT_ENV_FILE", raising=False)
    monkeypatch.delenv("MELT_TOKEN", raising=False)

    assert helper.load_environment() == tmp_path / ".env"
    assert os.environ["MELT_TOKEN"] == "from-working-dir"


def test_windows_clipboard_uses_powershell(monkeypatch) -> None:
    if os.name != "nt":
        return
    helper = load_helper()
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "日本語".encode())

    monkeypatch.delenv("MELT_CLIPBOARD_CMD", raising=False)
    monkeypatch.setattr(helper.subprocess, "run", fake_run)

    assert helper.read_clipboard() == "日本語"
    assert calls[0][0] == "powershell.exe"


def test_parse_windows_history_keeps_a_single_item() -> None:
    helper = load_helper()
    enabled, items = helper.parse_windows_history_json('{"enabled":true,"items":"only"}')
    assert enabled is True
    assert items == ["only"]


def test_select_bodies_posts_unseen_history_and_current(tmp_path) -> None:
    helper = load_helper()
    older = "old snippet"
    current = "current snippet"
    sent = {helper.body_hash(older)}
    chosen = helper.select_bodies_to_post([older, current], sent, set())
    assert chosen == [current]
    chosen_again = helper.select_bodies_to_post([older, current], set(), set())
    assert chosen_again == [older, current]
    queued = helper.select_bodies_to_post([older, current], set(), {current})
    assert queued == [older]


def test_batch_capture_posts_each_body(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MELT_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("MELT_LOCALE_DIR", str(ROOT / "locales"))
    helper = load_helper()
    posted: list[str] = []

    def fake_post(api, token, kind, body, key):
        posted.append(body)
        return 201, {"capture_id": "x", "occurrence_count": 1}

    monkeypatch.setattr(helper, "replay_queue", lambda *args, **kwargs: True)
    monkeypatch.setattr(helper, "capture_bodies", lambda *args, **kwargs: ["one", "two"])
    helper.post_capture = fake_post

    assert helper.main(["--no-notify"]) == 0
    assert posted == ["one", "two"]
    stored = json.loads((tmp_path / "sent-hashes.json").read_text(encoding="utf-8"))
    assert helper.body_hash("one") in stored
    assert helper.body_hash("two") in stored
