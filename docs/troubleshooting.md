# Troubleshooting

Every API error is one flat JSON object: `type`, `title`, `status`, `detail`, `code`. Helper toasts use the matching `error.<code>.*` keys in `locales/en.json`.

## auth

Token does not match `MELT_TOKEN`. Put the same value in `.env` and in the helper environment. Cookie name is `melt_token`.

## api_unreachable

The helper could not reach the API (network, timeout, or 5xx). `docker compose ps` and `curl -sS http://127.0.0.1:8080/healthz`. Remaining lines stay in `~/.local/state/melt/failed.jsonl`.

## clipboard_empty

No `text/plain` on the clipboard (empty, image, or HTML-only). Copy text and retry. `--stdin` reads stdin instead.

## too_large

Body is over 1 MiB UTF-8. Shrink it. The helper writes a dead-letter line with an empty body.

## too_long

The useful-for line is over 200 Unicode characters after NFC and newline folding. Shorten it. The source is unchanged.

## secret_blocked

The body matched a built-in token pattern (`ghp_`, `AKIA`, PEM, Slack, GitHub PAT). Set `MELT_ALLOW_SECRETS=1` or pass `--allow-secrets` if you really want to store it.

## locale_missing

The helper could not find `locales/en.json`. Set `MELT_LOCALE_DIR` to the repo `locales` directory, or use an absolute path to `scripts/melt-capture` inside the clone.

## empty

Body was empty after NFC trim (text) or URL canonicalize.

## bad_url

Not `http`/`https`, missing host, or userinfo in the URL.

## bad_kind

`kind` was not `url` or `text`. Omit `kind` and the server infers it.

## conflict_hash

SHA-256 collided with a different `kind` + normalized body. The request was not merged.

## conflict_idempotency

Same `Idempotency-Key` with a different body. Use a new key for a new capture.

## disk_full

SQLite raised `OperationalError` (disk full, locked too long). Check volume space.

## not_found

No such source or capture.

## bad_host

`Host` was not in `MELT_ALLOWED_HOSTS`, which defaults to `127.0.0.1,localhost`. Compose publishes localhost only. Reaching the API under another name means adding it to that list.

## bad_reuse

`kind` must be `copy_source` or `mark_used`.

## Helper files

| File | Meaning |
|---|---|
| `failed.jsonl` | retry on the next hotkey (5xx, network) |
| `failed.dead.jsonl` | 400/413 or oversize; not retried |
| `helper.lock` | one helper process at a time |

`python3 scripts/melt-capture --doctor` prints locale dir, token set, healthz, and clipboard binaries.
