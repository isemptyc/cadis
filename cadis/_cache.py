"""Cache directory resolution for Cadis control-layer operations."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_dir

_ENV_CACHE_DIR = "CADIS_CACHE_DIR"
_FALLBACK_CACHE_DIR = Path.home() / ".cache" / "cadis"


def resolve_cache_dir() -> Path:
    """Resolve cache path from env, OS defaults, then fallback."""
    env_value = os.getenv(_ENV_CACHE_DIR)
    if env_value and env_value.strip():
        return Path(env_value).expanduser()

    try:
        cache_dir = user_cache_dir(appname="cadis", appauthor="cadis")
        if cache_dir:
            return Path(cache_dir).expanduser()
    except Exception:
        pass

    return _FALLBACK_CACHE_DIR
