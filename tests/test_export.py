from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

from tests.conftest import TOKEN, auth_headers

ROOT = Path(__file__).resolve().parents[1]
SECRET_BODY = "clipboard body that must never reach the log"


def load_export() -> ModuleType:
    path = str(ROOT / "scripts" / "melt-export")
    loader = SourceFileLoader("melt_export_under_test", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def wired(client, monkeypatch) -> ModuleType:
    """The exporter, talking to the real API through the test client."""
    export = load_export()
    monkeypatch.setenv("MELT_API_URL", "http://testserver")
    monkeypatch.setenv("MELT_TOKEN", TOKEN)
    monkeypatch.setenv("MELT_ENV_FILE", "/nonexistent")

    def get_json(api: str, token: str, path: str) -> dict:
        response = client.get(path, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return response.json()

    export.get_json = get_json
    return export


def mirror_dir(tmp_path: Path) -> Path:
    """The client fixture keeps melt.db in tmp_path, so mirror into a subfolder."""
    out = tmp_path / "mirror"
    out.mkdir()
    return out


def capture(client, kind: str, body: str, key: str) -> dict:
    response = client.post("/v1/captures", json={"kind": kind, "body": body}, headers=auth_headers(key))
    assert response.status_code == 201
    return response.json()


def test_mirrors_each_source_once_and_rerun_writes_nothing(client, monkeypatch, tmp_path, capsys) -> None:
    export = wired(client, monkeypatch)
    tmp_path = mirror_dir(tmp_path)
    text = capture(client, "text", SECRET_BODY, "t1")
    url = capture(client, "url", "https://example.com/a", "u1")

    assert export.main(["--out", str(tmp_path)]) == 0
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == sorted([f"{text['source_id']}.md", f"{url['source_id']}.md"])

    note = (tmp_path / f"{text['source_id']}.md").read_text(encoding="utf-8")
    assert note.startswith("---\ntype: source\nschema_version: 1\n")
    assert f'latest_capture_id: "{text["capture_id"]}"' in note
    assert "privacy: private" in note
    assert "preservation: text-extracted" in note
    assert note.endswith(f"---\n\n{SECRET_BODY}\n")

    link = (tmp_path / f"{url['source_id']}.md").read_text(encoding="utf-8")
    assert 'source_url: "https://example.com/a"' in link
    assert "preservation: url-pointer" in link

    before = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()}
    assert export.main(["--out", str(tmp_path)]) == 0
    assert {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()} == before
    out = capsys.readouterr()
    assert "2 sources, 0 written" in out.out
    assert SECRET_BODY not in out.out + out.err


def test_recapture_moves_the_mirror_to_the_latest_capture(client, monkeypatch, tmp_path) -> None:
    export = wired(client, monkeypatch)
    tmp_path = mirror_dir(tmp_path)
    first = capture(client, "text", "same words", "r1")
    assert export.main(["--out", str(tmp_path)]) == 0
    second = capture(client, "text", "same words", "r2")
    assert second["source_id"] == first["source_id"]

    assert export.main(["--out", str(tmp_path)]) == 0
    note = (tmp_path / f"{first['source_id']}.md").read_text(encoding="utf-8")
    assert f'latest_capture_id: "{second["capture_id"]}"' in note
    assert "occurrence_count: 2" in note


def test_full_inbox_is_reported_as_incomplete(client, monkeypatch, tmp_path) -> None:
    export = wired(client, monkeypatch)
    tmp_path = mirror_dir(tmp_path)
    for i in range(export.INBOX_CAP):
        capture(client, "text", f"note {i}", f"n{i}")

    assert export.main(["--out", str(tmp_path)]) == 3
    assert len(list(tmp_path.iterdir())) == export.INBOX_CAP


def test_symlink_in_the_mirror_is_a_containment_failure(client, monkeypatch, tmp_path) -> None:
    export = wired(client, monkeypatch)
    source = capture(client, "text", "pointing elsewhere", "s1")
    target = tmp_path / "outside.txt"
    target.write_text("keep me", encoding="utf-8")
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    (mirror / f"{source['source_id']}.md").symlink_to(target)

    assert export.main(["--out", str(mirror)]) == 4
    assert target.read_text(encoding="utf-8") == "keep me"


def test_unexpected_source_id_is_a_containment_failure(monkeypatch, tmp_path) -> None:
    export = load_export()
    monkeypatch.setenv("MELT_API_URL", "http://testserver")
    monkeypatch.setenv("MELT_TOKEN", TOKEN)
    export.get_json = lambda api, token, path: {"rows": [{"source_id": "../../etc/passwd"}]}

    assert export.main(["--out", str(tmp_path)]) == 4
    assert list(tmp_path.iterdir()) == []


def test_missing_settings_exit_2(monkeypatch, tmp_path) -> None:
    export = load_export()
    monkeypatch.delenv("MELT_API_URL", raising=False)
    monkeypatch.delenv("MELT_TOKEN", raising=False)
    monkeypatch.setenv("MELT_ENV_FILE", "/nonexistent")

    assert export.main(["--out", str(tmp_path)]) == 2
    monkeypatch.setenv("MELT_API_URL", "http://testserver")
    monkeypatch.setenv("MELT_TOKEN", TOKEN)
    assert export.main(["--out", str(tmp_path / "missing")]) == 2
