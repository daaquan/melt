# Deferred from /autoplan 2026-08-28

- useful-for as a first-class capture field (zero-friction vs retrieval quality)
- LLM digest and URL snapshot worker (after ~10 mark-used, or a date gate)
- Spike: host helper → Karakeep vs building ingest
- MCP or stdout JSON as a read surface
- Disk-full SQLite path beyond generic 5xx
- GNOME shortcut cwd vs locale path E2E
- 1 MiB body inbox rendering
- `locales/` lives at the repo root, so a wheel install has no catalog and `t()` returns raw keys. Docker works because it copies the directory and sets `MELT_LOCALE_DIR`. Move the catalogs into the package when melt is installed any other way.
