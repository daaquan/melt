# melt

Clipboard capture for later. The source stays as you copied it. The digest is a derived stub, not a replacement.

Phase 1 is one FastAPI process, SQLite, a host helper, and an inbox at `http://127.0.0.1:8080`. No worker, no page snapshots, no LLM yet.

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
| `MELT_STATE_DIR` | helper | `$XDG_STATE_HOME/melt` or `~/.local/state/melt` |
| `MELT_ALLOW_SECRETS` | both | `0` (set `1` to store token-like text) |
| `MELT_ALLOWED_HOSTS` | API | `127.0.0.1,localhost` (the `Host` allowlist) |
| `MELT_CLIPBOARD_CMD` | helper | `wl-paste` on Wayland, else `xclip` |
| `MELT_NOTIFY_CMD` | helper | `notify-send` |

## Host helper

`scripts/melt-capture` is stdlib-only. It reads the clipboard (or `--stdin`), POSTs `http://127.0.0.1:8080/v1/captures`, and toasts from `locales/en.json`.

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

Flags: `--stdin`, `--doctor`, `--no-notify`, `--allow-secrets`. Failed 5xx/network lines go to `failed.jsonl` (mode 0600). 400/413 lines go to `failed.dead.jsonl`. A 401/403 during replay stops the run and does not POST the current clipboard.

## API

Auth: `Authorization: Bearer <MELT_TOKEN>` or cookie `melt_token` after `POST /v1/login`.

```bash
curl -sS -X POST http://127.0.0.1:8080/v1/captures \
  -H "Authorization: Bearer $MELT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind":"text","body":"hello melt"}'
```

`Idempotency-Key` is optional. The helper always sends one. Same key + same body returns the same `capture_id`. Same key + different body is `409`.

| Method | Path |
|---|---|
| GET | `/healthz` |
| POST | `/v1/captures` |
| GET | `/v1/search?q=` |
| GET | `/v1/sources/{id}` |
| POST | `/v1/sources/{id}/reuse` |
| POST | `/v1/captures/undo` |
| DELETE | `/v1/captures/{id}` |
| GET | `/` inbox |

Every error, from a route or from the size middleware, is one flat JSON object with `type`, `title`, `status`, `detail`, and `code`. Match on `code`. See [docs/troubleshooting.md](docs/troubleshooting.md).

The API answers only on `127.0.0.1` and `localhost`, which is what keeps a browser on some other page from talking to it. `MELT_ALLOWED_HOSTS` widens that if you knowingly bind past loopback.

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
