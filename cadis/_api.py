"""Public API facade for cadis."""

from __future__ import annotations

import re
from typing import Any

from ._cache import resolve_cache_dir
from ._errors import normalize_reason
from ._manager import get_manager

SCHEMA_VERSION = "1"
VERSION = "0.1.0"


def _to_iso2_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return sorted({str(v).upper() for v in value if str(v).strip()})
    return []


def _global_info_probe() -> tuple[list[str], list[str]]:
    """Best-effort static info probe with no lookup/bootstrap side effects."""
    system_iso2: list[str] = []
    offline_iso2: list[str] = _offline_iso2_from_cache()

    try:
        import cadis_global as module
    except Exception:
        return system_iso2, offline_iso2

    for attr_name in ("SYSTEM_ISO2", "DEFAULT_ISO2", "SUPPORTED_ISO2"):
        if not system_iso2 and hasattr(module, attr_name):
            system_iso2 = _to_iso2_list(getattr(module, attr_name))

    return system_iso2, offline_iso2


def _offline_iso2_from_cache() -> list[str]:
    """Derive cached ISO2s from local cache directory names."""
    path = resolve_cache_dir()
    if not path.exists() or not path.is_dir():
        return []

    iso2: list[str] = []
    for child in path.iterdir():
        if child.is_dir() and re.fullmatch(r"[A-Za-z]{2}", child.name):
            iso2.append(child.name.upper())

    return sorted(set(iso2))


def _failure_envelope(reason: Any) -> dict[str, Any]:
    return {
        "lookup_status": "failed",
        "engine": "cadis",
        "version": VERSION,
        "reason": normalize_reason(reason),
        "world_context": None,
        "admin_result": None,
    }


def lookup(lat: float, lon: float) -> dict[str, Any]:
    if not isinstance(lat, (float, int)) or not isinstance(lon, (float, int)):
        return _failure_envelope(ValueError("invalid coordinate type"))
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return _failure_envelope(ValueError("invalid coordinate range"))

    manager = get_manager()

    try:
        global_lookup = manager.get_or_init()
        result = global_lookup.lookup(float(lat), float(lon))
    except Exception as exc:
        return _failure_envelope(exc)

    if not isinstance(result, dict):
        return _failure_envelope("runtime_invalid_response")

    payload = dict(result)
    payload["engine"] = "cadis"
    payload["version"] = VERSION

    reason = payload.get("reason")
    if reason is not None:
        payload["reason"] = normalize_reason(reason)

    return payload


def info() -> dict[str, Any]:
    system_iso2, offline_iso2 = _global_info_probe()
    return {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "system_iso2": system_iso2,
        "offline_iso2": offline_iso2,
    }
