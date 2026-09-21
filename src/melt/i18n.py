from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path


def catalog_path() -> Path:
    env = os.environ.get("MELT_LOCALE_DIR")
    if env:
        candidate = Path(env) / "en.json"
        if candidate.is_file():
            return candidate
    here = Path(__file__).resolve()
    packaged = here.parent / "locales" / "en.json"
    if packaged.is_file():
        return packaged
    for parent in here.parents:
        candidate = parent / "locales" / "en.json"
        if candidate.is_file():
            return candidate
    return Path("locales/en.json")


@lru_cache
def load_catalog() -> dict:
    path = catalog_path()
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
