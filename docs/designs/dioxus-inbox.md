# Design: the inbox as a Dioxus client

Supersedes the inbox half of [phase1-capture-digest.md](./phase1-capture-digest.md)
and its locked sketch, [inbox-wireframe.html](./inbox-wireframe.html). Capture,
storage, dedup, and provenance are unchanged.

## What changed

The inbox was Jinja templates plus 50 lines of hand-written JS. Every action
was a form post answered with a 303 back to `/?selected=…`, and the query
string was the application state. That was the right call for one screen, and
it stopped scaling at the point where the page needed to do more than one
thing at a time.

It is now a [Dioxus](https://dioxuslabs.com) client compiled to WebAssembly.
FastAPI serves one static shell and JSON.

| Before | After |
|---|---|
| `templates/inbox.html`, `templates/login.html` | `src/melt/static/index.html` (fixed, no interpolation) |
| `static/inbox.js` | `ui/` → `src/melt/static/ui/melt_bg.wasm` |
| `POST …/context-form` → 303 | `POST …/context` → 204 |
| `POST …/reuse-form` → 302 | `POST …/reuse` |
| `POST …/{id}/delete-form` → 302 | `DELETE /v1/captures/{id}` |
| `GET /?q=&selected=` renders the list | `GET /v1/inbox?q=` returns the rows |
| — | `GET /v1/session`, `POST /v1/logout`, `GET /v1/i18n` |

The `-form` routes are gone rather than kept as a fallback: two renderings of
the same screen is the cost this change was meant to avoid, and the capture
path — the thing that has to keep working — never needed a browser.

## Why Dioxus and not plain JS

The alternative was to keep the templates and grow `inbox.js`. Rejected: the
interesting state (open capture, in-flight query, unsaved useful-for, optimistic
counts) is exactly the state that hand-rolled DOM code gets wrong, and it was
about to be written a third time. A reactive renderer makes that a signal
instead of a bug.

Rust specifically, over a JS framework: the repo already refuses a Node
toolchain, the whole client is 584 KB with no dependency tree to audit, and it
type-checks against the same problem-object contract the tests assert on.

Costs, accepted knowingly:

- **No inbox without JavaScript.** The API is unaffected, and the shell says so.
- **A compile step.** Handled by committing the bundle; see below.
- **584 KB.** Roughly 210 KB over the wire gzipped, cached after the first load,
  on a service that runs on loopback or a personal tailnet.

## Build and distribution

`scripts/build-ui.sh` builds `ui/` and writes `src/melt/static/ui/`, which is
**committed**. `pip install melt` and `docker compose up --build` stay
toolchain-free; only someone editing `ui/` needs Rust.

Committed build output rots silently, so CI rebuilds it and diffs
(`scripts/build-ui.sh --check`). That check is only meaningful if the build is
reproducible, which is why the toolchain is pinned in `ui/rust-toolchain.toml`,
`wasm-bindgen` is pinned by `ui/Cargo.lock`, and there is no `wasm-opt` pass —
an optimizer that only some contributors have installed would turn the check
into noise. Verified byte-identical across different checkout paths.

## Security

- CSP widens by exactly one token: `script-src 'self' 'wasm-unsafe-eval'`.
  That permits `WebAssembly.instantiate`; `eval()` stays blocked, and there is
  still no `unsafe-inline`. Both loader scripts are files for that reason.
- The shell interpolates nothing. Capture bodies reach the browser as JSON and
  enter the DOM as text nodes, so the escaping bug class the old template had
  to defend against does not exist. `test_shell_never_carries_capture_text`
  pins that by asserting the page is byte-identical with and without a capture
  holding a script tag.
- The token still never touches client state: the login form posts to the same
  `/v1/login`, and the session lives in the same HttpOnly cookie. That route
  answers by `Accept`: 204 to the client's fetch, which would otherwise follow
  the redirect and pull the whole shell down again, and the 302 to `/` to a
  plain form post, which has nowhere else to go.
- `GET /v1/session` and `GET /v1/i18n` answer without auth. Neither returns
  capture data; the sign-in screen needs both before a session exists.

## Two things worth knowing

**Preview vs. copy.** A body may be 1 MiB and the client opens a capture on
every arrow key. `GET /v1/sources/{id}?preview=1` caps the body at
`DISPLAY_CHARS` (20,000) and reports `raw_chars` and `truncated`. Copy-to-
clipboard refetches without `preview`, so the clipboard always gets the whole
source — the same split the old page had, where the template rendered 20,000
characters and `inbox.js` fetched the rest.

**Strings stay in `locales/`.** The client ships keys only and reads the
catalog from `/v1/i18n` at boot, so the design rule that no user-facing English
lives in source still holds — now for Rust as well as Python. A missing key
renders as the key.

## Design

Tokens in `src/melt/static/app.css`: one light palette on `:root`, one dark,
applied by `prefers-color-scheme` and overridable with `<html data-theme>`. A
classic `theme-boot.js` in `<head>` replays a pinned theme before first paint so
dark does not flash light. No web fonts — the CSP forbids third-party origins
and a local tool should not wait on a CDN.

Beyond the port: live search with a 160 ms debounce (the in-flight request is
dropped, not queued), `j`/`k` and arrow navigation, toasts in place of
navigation as feedback, an in-app delete dialog instead of `window.confirm`,
skeleton rows on first load, relative timestamps, a used marker and the
useful-for line in the list, and a single-pane phone layout where the list and
the open capture swap.

Single-key shortcuts are muted whenever a text field has focus. That is also
what makes IME composition safe — a half-typed Japanese word can never reach
the `j`/`k` handler — which the old `event.isComposing` check handled.
