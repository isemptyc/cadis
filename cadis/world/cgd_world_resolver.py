"""CGD-backed world resolver for cadis.world."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cgd_binary import (
    FLAG_COUNTRY,
    FLAG_LANDMASS,
    FLAG_OCEAN,
    TERMINAL_ANTARCTICA,
    TERMINAL_NO_SOVEREIGN_LAND,
    TERMINAL_OPEN_SEA,
    CGDReader,
)


class CGDWorldResolver:
    """Resolve world context using a CGD binary dataset."""

    SOURCE = "cgd"
    OPEN_SEA_LABEL = "Open Sea"
    ANTARCTICA_LABEL = "Antarctica"
    NO_SOVEREIGN_LAND_LABEL = "No Sovereign Land"

    def __init__(self, *, cgd_path: Path):
        self._reader = CGDReader(Path(cgd_path))
        self._FLAG_COUNTRY = FLAG_COUNTRY
        self._FLAG_OCEAN = FLAG_OCEAN
        self._FLAG_LANDMASS = FLAG_LANDMASS
        self._TERMINAL_OPEN_SEA = TERMINAL_OPEN_SEA
        self._TERMINAL_ANTARCTICA = TERMINAL_ANTARCTICA
        self._TERMINAL_NO_SOVEREIGN_LAND = TERMINAL_NO_SOVEREIGN_LAND

    def resolve(self, lat: float, lon: float) -> dict[str, Any]:
        """Resolve point to country or world terminal state envelope."""
        resolved_at = datetime.now(timezone.utc).isoformat()
        hit = self._reader.lookup(lon, lat)

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
