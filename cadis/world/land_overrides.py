"""Small sovereign-land overrides for CGD coastal/island gaps."""

from __future__ import annotations

import importlib.resources
import json
from dataclasses import dataclass
from typing import Any

from .cgd_binary import _polygon_covers


@dataclass(frozen=True)
class LandOverrideHit:
    iso2: str
    country_name: str
    override_id: str
    override_name: str
    source: str


@dataclass(frozen=True)
class _LandOverride:
    override_id: str
    name: str
    iso2: str
    country_name: str
    source: str
    bbox: tuple[float, float, float, float]
    rings: list[list[list[float]]]


class LandOverrideIndex:
    """Point-in-polygon index for explicit land fixes not represented in CGD."""

    def __init__(self, overrides: list[_LandOverride]):
        self._overrides = tuple(overrides)

    @classmethod
    def from_bundled(cls) -> "LandOverrideIndex":
        try:
            raw = (
                importlib.resources.files("cadis.world")
                .joinpath("data")
                .joinpath("land_overrides.json")
                .read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return cls([])
        payload = json.loads(raw)
        rows = payload.get("overrides")
        if not isinstance(rows, list):
            return cls([])

        overrides: list[_LandOverride] = []
        for row in rows:
            parsed = _parse_override(row)
            if parsed is not None:
                overrides.append(parsed)
        return cls(overrides)

    def lookup(self, lat: float, lon: float) -> LandOverrideHit | None:
        for override in self._overrides:
            min_lon, min_lat, max_lon, max_lat = override.bbox
            if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                continue
            if not _polygon_covers(lon, lat, override.rings):
                continue
            return LandOverrideHit(
                iso2=override.iso2,
                country_name=override.country_name,
                override_id=override.override_id,
                override_name=override.name,
                source=override.source,
            )
        return None

    def country_bbox_candidates(self, lat: float, lon: float) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for override in self._overrides:
            min_lon, min_lat, max_lon, max_lat = override.bbox
            if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                continue
            if override.iso2 not in seen:
                seen.add(override.iso2)
                out.append(override.iso2)
        return out


def _parse_override(row: Any) -> _LandOverride | None:
    if not isinstance(row, dict):
        return None
    country = row.get("country")
    geometry = row.get("geometry")
    bbox = row.get("bbox")
    if not isinstance(country, dict) or not isinstance(geometry, dict):
        return None
    if geometry.get("type") != "Polygon":
        return None
    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or not coords:
        return None
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None

    iso2 = country.get("iso2")
    country_name = country.get("name")
    override_id = row.get("id")
    name = row.get("name")
    source = row.get("source")
    if not all(isinstance(value, str) and value.strip() for value in (iso2, country_name, override_id, name, source)):
        return None

    try:
        parsed_bbox = tuple(float(value) for value in bbox)
        rings = [
            [[float(point[0]), float(point[1])] for point in ring]
            for ring in coords
            if isinstance(ring, list)
        ]
    except (TypeError, ValueError, IndexError):
        return None
    if len(parsed_bbox) != 4 or not rings:
        return None
    return _LandOverride(
        override_id=override_id.strip(),
        name=name.strip(),
        iso2=iso2.strip().upper(),
        country_name=country_name.strip(),
        source=source.strip(),
        bbox=parsed_bbox,  # type: ignore[arg-type]
        rings=rings,
    )
