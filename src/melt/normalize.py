from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_BYTES = 1_048_576
URL_RE = re.compile(r"^https?://\S+$")
DROP_QUERY_EXACT = {"fbclid", "gclid"}


class NormalizeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def infer_kind(body: str) -> str:
    trimmed = body.strip()
    return "url" if URL_RE.match(trimmed) else "text"


def canonicalize_url(raw: str) -> str:
    parsed = urlsplit(raw.strip())
    if parsed.scheme not in ("http", "https"):
        raise NormalizeError("bad_url", "URL must use http or https")
    if parsed.username or parsed.password:
        raise NormalizeError("bad_url", "URL must not include userinfo")
    host = parsed.hostname
    if not host:
        raise NormalizeError("bad_url", "URL must include a host")
    host = host.lower()
    port = parsed.port
    default = (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    )
    netloc = host if (port is None or default) else f"{host}:{port}"
    if ":" in host and not host.startswith("["):
        netloc = f"[{host}]" if port is None or default else f"[{host}]:{port}"
    # Drop slash only on the site root. /path/ and /path stay distinct.
    path = "" if parsed.path in {"", "/"} else parsed.path
    pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lower = key.lower()
        if lower.startswith("utm_") or lower in DROP_QUERY_EXACT:
            continue
        pairs.append((key, value))
    pairs.sort(key=lambda item: item[0])
    query = urlencode(pairs, doseq=True)
    return urlunsplit((parsed.scheme, netloc, path, query, parsed.fragment))


def normalize_text(raw: str) -> str:
    return unicodedata.normalize("NFC", raw).strip()


def normalize(kind: str, body: str) -> tuple[str, str]:
    if kind not in ("url", "text"):
        raise NormalizeError("bad_kind", "kind must be url or text")
    if len(body.encode("utf-8")) > MAX_BYTES:
        raise NormalizeError("too_large", "body exceeds 1 MiB")
    if kind == "url":
        normalized = canonicalize_url(body)
    else:
        normalized = normalize_text(body)
    if not normalized:
        raise NormalizeError("empty", "body is empty after normalize")
    return kind, normalized


def source_hash(kind: str, normalized_body: str) -> str:
    payload = f"{kind}\n{normalized_body}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def stub_phrases(text: str, cap: int = 50) -> list[str]:
    tokens = re.findall(r"\S{4,}", text)
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= cap:
            break
    return out


def fts_query(q: str) -> str | None:
    parts: list[str] = []
    for token in q.split():
        escaped = token.replace('"', '""')
        parts.append(f'"{escaped}"')
    if not parts:
        return None
    return " AND ".join(parts)


CONTEXT_MAX = 200


def normalize_context(raw: str) -> str:
    """One-line useful-for. Empty after this is a delete, not an error.

    NFC, then newlines become spaces, then trim. Length is Unicode code
    points (`len` of the str), not UTF-8 bytes — a short sentence cap, not
    the 1 MiB ingest limit. Do not call `normalize()`; that path rejects empty
    and is for source identity.
    """
    body = unicodedata.normalize("NFC", raw)
    body = body.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    body = body.strip()
    if len(body) > CONTEXT_MAX:
        raise NormalizeError("too_long", "context exceeds 200 characters")
    return body
