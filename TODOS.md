# Deferred from /autoplan 2026-08-28

- useful-for as a first-class capture field (zero-friction vs retrieval quality)
- LLM digest and URL snapshot worker (after ~10 mark-used, or a date gate)
- Spike: host helper → Karakeep vs building ingest
- MCP or stdout JSON as a read surface
- Disk-full SQLite path beyond generic 5xx
- GNOME shortcut cwd vs locale path E2E
- ~~1 MiB body inbox rendering~~ — done: `/v1/sources/{id}?preview=1` caps
  the rendered body at 20,000 chars and Copy refetches the whole source
- Translate `locales/ja.json`; it is still an English copy, and the client
  has no locale picker yet (it always serves `en.json`)
