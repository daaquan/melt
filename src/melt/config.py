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


def allowed_hosts() -> frozenset[str]:
    """Host header allowlist. This is the DNS rebinding guard.

    Widen it only if you knowingly bind past loopback.
    """
    raw = os.environ.get("MELT_ALLOWED_HOSTS", "127.0.0.1,localhost")
    return frozenset(h.strip() for h in raw.split(",") if h.strip())


def trust_proxy() -> bool:
    """Honor X-Forwarded-Proto when TLS terminates in front of melt."""
    return os.environ.get("MELT_TRUST_PROXY", "0") == "1"
