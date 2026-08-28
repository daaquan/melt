# melt

Clipboard capture for later. The source stays as you copied it. The digest is a derived stub, not a replacement.

Phase 1 is one FastAPI process, SQLite, and an inbox. Capture clients are anything that can `POST /v1/captures` with the token: the host helper, curl, or an iPad Shortcut. No worker, no page snapshots, no LLM yet.

After capture, open the inbox and type a one-line **useful for** under the source (`n` focuses the field). Search uses your words as well as the clipboard text. The list title stays the source preview; the digest stays a derived stub.

## Quickstart

```bash
git clone git@github.com:daaquan/melt.git && cd melt
cp .env.example .env
# put a token on the MELT_TOKEN= line
openssl rand -hex 32
docker compose up --wait --build
set -a && source .env && set +a
export MELT_API_URL=http://127.0.0.1:8080
printf '%s' 'hello melt' | python3 scripts/melt-capture --stdin --no-notify
xdg-open http://127.0.0.1:8080
```

Log in with the same `MELT_TOKEN`. You should see `hello melt` in the list.

If the helper prints `Failed`, run `python3 scripts/melt-capture --doctor`.

## Config

| Variable | Who | Default |
|---|---|---|
| `MELT_TOKEN` | API and helper | required |
| `MELT_API_URL` | helper | `http://127.0.0.1:8080` |
| `MELT_BIND` / `MELT_PORT` | compose publish | `127.0.0.1` / `8080` |
| `MELT_DB_PATH` | API | `melt.db` (compose: `/data/melt.db`) |
| `MELT_LOCALE_DIR` | API and helper | walk up from the file to `locales/` |
| `MELT_STATE_DIR` | helper | Linux: `$XDG_STATE_HOME/melt` or `~/.local/state/melt`; Windows: `%LOCALAPPDATA%\melt` |
| `MELT_ALLOW_SECRETS` | both | `0` (set `1` to store token-like text) |
| `MELT_ALLOWED_HOSTS` | API | `127.0.0.1,localhost` (add the public hostname when TLS is in front) |
| `MELT_TRUST_PROXY` | API | `0` (set `1` so login cookies get `Secure` behind a reverse proxy) |
| `MELT_CLIPBOARD_CMD` | helper | Windows PowerShell; Linux: `wl-paste` on Wayland, else `xclip` |
| `MELT_NOTIFY_CMD` | helper | Windows notification balloon; Linux: `notify-send` |

## Host helper

`scripts/melt-capture` is stdlib-only and runs on Windows and Linux. It reads the clipboard (or `--stdin`), POSTs `http://127.0.0.1:8080/v1/captures`, and shows a notification from `locales/en.json`. On Windows it also sends every **text** item in clipboard history (Win+V), oldest first, then the current clipboard. Already-ingested history is skipped so a second hotkey does not multiply occurrences; the current clipboard is still posted so recapture counts. Images and HTML-only history rows are skipped. Turn clipboard history on in Settings → System → Clipboard, or `Win+V`.

### Windows

Start the API in Docker Desktop, then check the helper:

```powershell
python -m venv .venv
.\scripts\melt-capture-windows.cmd --doctor
```

The helper is one shot, not a background app: each run saves clipboard history (and the current clipboard) then exits, which is why a console window only flashes. Register the hotkey to run it:

```powershell
.\scripts\install-windows-hotkey.ps1
```

That writes a Start Menu shortcut with `Ctrl+Alt+M`, running the helper through `pythonw.exe` so no window appears. Windows only honours a shortcut's hotkey from the Start Menu or the Desktop, so a shortcut left anywhere else silently does nothing. Pass `-Hotkey "CTRL+ALT+K"` for a different key, or `-Remove` to unregister.

Copy some text, press the hotkey, and a balloon reports the result (`Saved 12` when several history items land). Settings come from `.env` in the shortcut's working directory, so the helper and Compose share one `MELT_TOKEN`. Only helper settings are read from that file; `MELT_DB_PATH` and other server values are ignored. Failed captures stay under `%LOCALAPPDATA%\melt`.

To build a standalone executable instead:

```powershell
.\scripts\build-windows.ps1
.\dist\melt-capture.exe --doctor
```

The executable reads `.env` beside it or in its parent directory. For a downloaded CI artifact, rename `.env.example` to `.env`, set `MELT_TOKEN`, and keep both together. Managed Windows installations may block an unsigned local build; use the hotkey shortcut or sign the executable with your organization's certificate.

### Linux

Use an **absolute path** in shortcuts. GNOME often starts the command with `$HOME` as cwd, so `scripts/melt-capture` will miss `locales/` unless you set `MELT_LOCALE_DIR`.

### GNOME

Settings → Keyboard → Custom Shortcut. Name `melt`. Command (edit the repo path):

```bash
env MELT_TOKEN=… MELT_API_URL=http://127.0.0.1:8080 MELT_LOCALE_DIR=/opt/melt/locales /opt/melt/scripts/melt-capture
```

Suggested key: `Ctrl+Alt+M`.

### sxhkd

```
ctrl + alt + m
    /opt/melt/scripts/melt-capture
```

Export `MELT_TOKEN`, `MELT_API_URL`, and `MELT_LOCALE_DIR` from your session (`.profile` or the sxhkd service).

### Hyprland

```
bind = CTRL ALT, M, exec, /opt/melt/scripts/melt-capture
```

Same env as above.

Flags: `--stdin`, `--doctor`, `--no-notify`, `--allow-secrets`. Failed 5xx/network lines go to `failed.jsonl` (mode 0600). 400/413 lines go to `failed.dead.jsonl`. A 401/403 during replay stops the run and does not POST live clipboard items. `--stdin` still sends one payload and does not read Windows history.

## API

One token, one inbox. Any client that can make HTTPS (or localhost HTTP) is enough. There are no per-device accounts yet.

```bash
curl -sS -X POST https://melt.example.com/v1/captures \
  -H "Authorization: Bearer $MELT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind":"text","body":"hello melt"}'
```

On the machine that runs Compose, keep `MELT_BIND=127.0.0.1` and put Caddy, nginx, or Tailscale Serve in front with TLS. Then:

- `MELT_ALLOWED_HOSTS=127.0.0.1,localhost,melt.example.com`
- `MELT_TRUST_PROXY=1` so the inbox login cookie is `Secure`
- helpers and phones set `MELT_API_URL=https://melt.example.com` (or the same URL in Shortcuts)

Do not publish `0.0.0.0:8080` on the internet. The token is full access to every capture.

### iPad / iPhone (Shortcuts)

1. New Shortcut → add **Get Contents of URL**.
2. URL `https://melt.example.com/v1/captures`, method POST.
3. Headers: `Authorization` = `Bearer ` + the token, `Content-Type` = `application/json`.
4. Request body JSON: `{"kind":"text","body":"..."}` and put the shared text in `body`.
5. Use **Receive Text** / Share Sheet so Safari or Notes can send a snippet.

The same POST works from any other app that can set those headers. The Windows/Linux helper is only a clipboard reader in front of this route.

`Idempotency-Key` is optional. The helper always sends one. Same key + same body returns the same `capture_id`. Same key + different body is `409`.

| Method | Path |
|---|---|
| GET | `/healthz` |
| POST | `/v1/captures` |
| GET | `/v1/search?q=` |
| GET | `/v1/sources/{id}` |
| POST | `/v1/sources/{id}/context` |
| POST | `/v1/sources/{id}/context-form` |
| POST | `/v1/sources/{id}/reuse` |
| POST | `/v1/captures/undo` |
| DELETE | `/v1/captures/{id}` |
| GET | `/` inbox |

Every error, from a route or from the size middleware, is one flat JSON object with `type`, `title`, `status`, `detail`, and `code`. Match on `code`. See [docs/troubleshooting.md](docs/troubleshooting.md).

The API answers only for hostnames in `MELT_ALLOWED_HOSTS` (default `127.0.0.1` and `localhost`). That is the DNS-rebinding guard. Add the public name when a reverse proxy is in front; leave Compose published on loopback.

## Dev without Docker

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
export MELT_TOKEN=$(openssl rand -hex 32)
.venv/bin/uvicorn melt.app:app --reload --host 127.0.0.1 --port 8080
```

```bash
.venv/bin/pytest
```

## License

Apache-2.0. See [CONTRIBUTING.md](CONTRIBUTING.md).
