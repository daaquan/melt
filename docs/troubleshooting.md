# Troubleshooting

Every API error is one flat JSON object: `type`, `title`, `status`, `detail`, `code`. Helper toasts use the matching `error.<code>.*` keys in `locales/en.json`.

## auth

Token does not match `MELT_TOKEN`. Put the same value in `.env` and in the helper environment. Cookie name is `melt_token`.

## api_unreachable

The helper could not reach the API (network, timeout, or 5xx). `docker compose ps` and `curl -sS http://127.0.0.1:8080/healthz`. Remaining lines stay in `~/.local/state/melt/failed.jsonl`.

## 403 from a CDN

A `403` whose body is not melt's JSON comes from the CDN in front of the API, not from melt. Cloudflare blocks the default `Python-urllib/*` agent, so the helper sends `User-Agent: melt-capture/0.1`. Any other client behind the same CDN has to set its own agent string.

## clipboard_empty

No `text/plain` on the clipboard (empty, image, or HTML-only). Copy text and retry. `--stdin` reads stdin instead. On Windows, clipboard history must be on (`Win+V`) for older copies to be sent; only text items are posted.

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

`Host` was not in `MELT_ALLOWED_HOSTS`, which defaults to `127.0.0.1,localhost`. Compose should stay on loopback. A reverse proxy hostname has to be on that list. Inbox login over HTTPS also needs `MELT_TRUST_PROXY=1` so the session cookie is marked `Secure`.

## bad_reuse

`kind` must be `copy_source` or `mark_used`.

## error

The request failed without a named code — a path that is not a melt route, or
a framework error raised before a handler ran. The status says which. Check the
URL first.

## unknown

The inbox got a failure whose `code` is not in `locales/en.json`. The status is
still in the response; read it from the browser devtools network tab and look
the code up above. Adding the missing `error.<code>.*` keys fixes the message.

## The inbox is blank

The page is a shell; the UI itself is a WebAssembly module. Open devtools and
check, in order:

- **A `Content-Security-Policy` violation on `wasm-unsafe-eval`.** A reverse
  proxy that rewrites CSP headers will strip it and the module never compiles.
  melt sends `script-src 'self' 'wasm-unsafe-eval'`; let it through unchanged.
- **`/static/ui/melt_bg.wasm` served as anything but `application/wasm`.**
  `X-Content-Type-Options: nosniff` means the browser will not guess, and
  `instantiateStreaming` refuses the response. Some proxies mangle this.
- **404 on `/static/ui/melt.js`.** The bundle is missing from the install. It is
  committed, so this means a partial checkout or a wheel built before the UI
  existed. Run `scripts/build-ui.sh`.

Captures are unaffected either way: `POST /v1/captures` and the rest of `/v1`
are plain JSON and do not need the client.

## Helper files

| File | Meaning |
|---|---|
| `failed.jsonl` | retry on the next hotkey (5xx, network) |
| `failed.dead.jsonl` | 400/413 or oversize; not retried |
| `helper.lock` | one helper process at a time |

`python3 scripts/melt-capture --doctor` prints locale dir, token set, healthz, and clipboard binaries.
