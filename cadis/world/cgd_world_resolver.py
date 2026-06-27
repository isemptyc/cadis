"""CGD-backed world resolver for cadis.world."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cgd_backend import create_cgd_reader
from .cgd_binary import (
    CGDReader,
    FLAG_COUNTRY,
    FLAG_LANDMASS,
    FLAG_OCEAN,
    TERMINAL_ANTARCTICA,
    TERMINAL_NO_SOVEREIGN_LAND,
    TERMINAL_OPEN_SEA,
)


class CGDWorldResolver:
    """Resolve world context using a CGD binary dataset."""

    SOURCE = "cgd"
    OPEN_SEA_LABEL = "Open Sea"
    ANTARCTICA_LABEL = "Antarctica"
    NO_SOVEREIGN_LAND_LABEL = "No Sovereign Land"

    def __init__(self, *, cgd_path: Path):
        self._reader = create_cgd_reader(Path(cgd_path))
        self._backend_name = "python" if isinstance(self._reader, CGDReader) else "native"
        self._FLAG_COUNTRY = FLAG_COUNTRY
        self._FLAG_OCEAN = FLAG_OCEAN
        self._FLAG_LANDMASS = FLAG_LANDMASS
        self._TERMINAL_OPEN_SEA = TERMINAL_OPEN_SEA
        self._TERMINAL_ANTARCTICA = TERMINAL_ANTARCTICA
        self._TERMINAL_NO_SOVEREIGN_LAND = TERMINAL_NO_SOVEREIGN_LAND

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def resolve(self, lat: float, lon: float) -> dict[str, Any]:
        """Resolve point to country or world terminal state envelope."""
        hit = self._reader.lookup(lon, lat)
        return self._world_context_from_hit(hit, resolved_at=datetime.now(timezone.utc).isoformat())

    def country_bbox_candidates(self, lat: float, lon: float) -> list[str]:
        """Supported-country ISO2s whose CGD bbox contains the point (most-specific first).

        Returns ``[]`` on backends that don't expose it (e.g. the native kernel).
        """
        fn = getattr(self._reader, "country_bbox_candidates", None)
        if fn is None:
            return []
        try:
            return list(fn(lon, lat))
        except Exception:
            return []

    def resolve_many_lons_lats(self, lons: object, lats: object) -> list[dict[str, Any]]:
        """Resolve a batch of lon/lat sequences, preserving input order."""
        resolved_at = datetime.now(timezone.utc).isoformat()
        if hasattr(self._reader, "lookup_many_lons_lats"):
            hits = self._reader.lookup_many_lons_lats(lons, lats)
        else:
            lon_values = list(lons)  # type: ignore[arg-type]
            lat_values = list(lats)  # type: ignore[arg-type]
            if len(lon_values) != len(lat_values):
                raise ValueError("lons and lats must have the same length")
            hits = [self._reader.lookup(float(lon), float(lat)) for lon, lat in zip(lon_values, lat_values)]
        return [self._world_context_from_hit(hit, resolved_at=resolved_at) for hit in hits]

    def _world_context_from_hit(self, hit: Any, *, resolved_at: str) -> dict[str, Any]:
        if hit is None:
            return {
                "lookup_status": "ok",
                "source": self.SOURCE,
                "resolved_at": resolved_at,
                "resolution_method": "open_sea",
                "world_result": {
                    "type": "open_sea",
                    "name": self.OPEN_SEA_LABEL,
                },
            }

        flags = int(hit.get("flags") or 0)
        terminal_code = int(hit.get("terminal_code") or 0)
        name = str(hit.get("name") or "")
        iso2 = str(hit.get("iso2_code") or "")

        if terminal_code == self._TERMINAL_ANTARCTICA:
            return {
                "lookup_status": "ok",
                "source": self.SOURCE,
                "resolved_at": resolved_at,
                "resolution_method": "antarctica",
                "country": {
                    "iso2": iso2 or "AQ",
                    "name": name or self.ANTARCTICA_LABEL,
                },
                "world_result": {
                    "type": "antarctica",
                    "name": self.ANTARCTICA_LABEL,
                },
            }

        if terminal_code == self._TERMINAL_NO_SOVEREIGN_LAND or (flags & self._FLAG_LANDMASS):
            return {
                "lookup_status": "ok",
                "source": self.SOURCE,
                "resolved_at": resolved_at,
                "resolution_method": "no_sovereign_land",
                "world_result": {
                    "type": "no_sovereign_land",
                    "name": name or self.NO_SOVEREIGN_LAND_LABEL,
                },
            }

        if terminal_code == self._TERMINAL_OPEN_SEA or (flags & self._FLAG_OCEAN):
            return {
                "lookup_status": "ok",
                "source": self.SOURCE,
                "resolved_at": resolved_at,
                "resolution_method": "open_sea",
                "world_result": {
                    "type": "open_sea",
                    "name": name or self.OPEN_SEA_LABEL,
                },
            }

        if flags & self._FLAG_COUNTRY and iso2:
            return {
                "lookup_status": "ok",
                "source": self.SOURCE,
                "resolved_at": resolved_at,
                "country": {
                    "iso2": iso2,
                    "name": name or iso2,
                },
            }

        return {
            "lookup_status": "ok",
            "source": self.SOURCE,
            "resolved_at": resolved_at,
            "resolution_method": "open_sea",
            "world_result": {
                "type": "open_sea",
                "name": name or self.OPEN_SEA_LABEL,
            },
        }
