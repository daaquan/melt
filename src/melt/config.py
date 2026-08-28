from __future__ import annotations

import os
from pathlib import Path

COOKIE_NAME = "melt_token"


def max_bytes() -> int:
    return int(os.environ.get("MELT_MAX_BYTES", "1048576"))


def token() -> str:
    return os.environ.get("MELT_TOKEN", "")


def db_path() -> Path:
    return Path(os.environ.get("MELT_DB_PATH", "melt.db"))


def allow_secrets() -> bool:
    return os.environ.get("MELT_ALLOW_SECRETS", "0") == "1"
