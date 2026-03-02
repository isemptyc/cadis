"""Internal singleton manager around cadis-global."""

from __future__ import annotations

import threading
from pathlib import Path

from ._cache import resolve_cache_dir
from ._errors import normalize_reason


class CadisManager:
    """Process-level manager for a single GlobalLookup instance."""

    def __init__(self) -> None:
        self._lookup = None
        self._lock = threading.Lock()

    def is_initialized(self) -> bool:
        return self._lookup is not None

    def get_or_init(self):
        if self._lookup is not None:
            return self._lookup

        with self._lock:
            if self._lookup is not None:
                return self._lookup

            try:
                from cadis_global import GlobalLookup
            except Exception as exc:  # pragma: no cover - exercised via tests with import stubs
                raise ImportError(normalize_reason(exc)) from None

            cache_dir: Path = resolve_cache_dir()

            try:
                self._lookup = GlobalLookup.from_defaults(
                    cache_dir=cache_dir,
                    update_to_latest=False,
                )
            except Exception as exc:
                raise RuntimeError(normalize_reason(exc)) from None

            return self._lookup


_MANAGER = CadisManager()


def get_manager() -> CadisManager:
    return _MANAGER
