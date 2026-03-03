"""Internal CGD binary reader for bundled world dataset."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CGD_MAGIC = b"CGD\x01\x00\x00\x00\x00"
SPEC_MAJOR = 1

HEADER_STRUCT = struct.Struct("<8sHHIIIQQQQQ")
POLYGON_INDEX_STRUCT = struct.Struct("<IQII2sBHB")
BBOX_STRUCT = struct.Struct("<ffff")
STRING_OFFSET_STRUCT = struct.Struct("<QII")

FLAG_COUNTRY = 1 << 0
FLAG_OCEAN = 1 << 1
FLAG_LANDMASS = 1 << 2

TERMINAL_NONE = 0
TERMINAL_OPEN_SEA = 1
TERMINAL_ANTARCTICA = 2
TERMINAL_NO_SOVEREIGN_LAND = 3


@dataclass(frozen=True)
class _IndexRec:
    bbox_index: int
    geom_offset: int
    ring_count: int
    string_index: int
    iso2: str
    terminal_code: int
    flags: int


@dataclass(frozen=True)
class _PolygonRec:
    bbox: tuple[float, float, float, float]
    rings: list[list[tuple[float, float]]]
    iso2: str
    terminal_code: int
    flags: int
    name: str


def _point_on_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> bool:
    eps = 1e-12
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > eps:
        return False
    dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
    if dot < -eps:
        return False
    seg_len_sq = (bx - ax) ** 2 + (by - ay) ** 2
    return dot - seg_len_sq <= eps


def _ring_covers(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if _point_on_segment(lon, lat, x1, y1, x2, y2):
            return True
        if (y1 > lat) != (y2 > lat):
            x_at_lat = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if x_at_lat == lon:
                return True
            if x_at_lat > lon:
                inside = not inside
    return inside


def _polygon_covers(lon: float, lat: float, rings: list[list[tuple[float, float]]]) -> bool:
    if not rings:
        return False
    if not _ring_covers(lon, lat, rings[0]):
        return False
    for hole in rings[1:]:
        if _ring_covers(lon, lat, hole):
            return False
    return True


class CGDReader:
    """CGD reader that preloads records for repeated lookups."""

    def __init__(self, path: Path):
        self._path = Path(path)
        if not self._path.exists():
            raise FileNotFoundError(f"CGD file not found: {self._path}")
        self._polygons = self._load_all(self._path.read_bytes())

    def lookup(self, lon: float, lat: float) -> Optional[dict]:
        generic_ocean_labels = {"ocean", "open sea"}
        first_hit: Optional[dict] = None
        best_named_ocean: Optional[dict] = None
        best_named_ocean_bbox_area: float | None = None

        for idx, poly in enumerate(self._polygons):
            min_lon, min_lat, max_lon, max_lat = poly.bbox
            if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                continue
            if not _polygon_covers(lon, lat, poly.rings):
                continue

            hit = {
                "polygon_index": idx,
                "iso2_code": poly.iso2 or None,
                "terminal_code": poly.terminal_code,
                "flags": poly.flags,
                "name": poly.name,
            }
            if first_hit is None:
                first_hit = hit

            # Preserve deterministic country precedence.
            if poly.flags & FLAG_COUNTRY:
                return hit

            is_oceanish = (poly.flags & FLAG_OCEAN) or (poly.terminal_code == TERMINAL_OPEN_SEA)
            if not is_oceanish:
                continue

            lowered = (poly.name or "").strip().lower()
            if lowered in generic_ocean_labels:
                continue

            bbox_area = (max_lon - min_lon) * (max_lat - min_lat)
            if (
                best_named_ocean is None
                or best_named_ocean_bbox_area is None
                or bbox_area < best_named_ocean_bbox_area
            ):
                best_named_ocean = hit
                best_named_ocean_bbox_area = bbox_area

        if best_named_ocean is not None:
            return best_named_ocean
        return first_hit

    def _load_all(self, data: bytes) -> list[_PolygonRec]:
        if len(data) < HEADER_STRUCT.size:
            raise ValueError("CGD file too small")

        (
            magic,
            spec_major,
            _spec_minor,
            polygon_count,
            string_count,
            _reserved,
            offset_polygon_index,
            offset_bbox_table,
            _offset_geometry_blob,
            offset_string_offset_table,
            _offset_string_blob,
        ) = HEADER_STRUCT.unpack_from(data, 0)

        if magic != CGD_MAGIC:
            raise ValueError("Invalid CGD magic")
        if spec_major != SPEC_MAJOR:
            raise ValueError(f"Unsupported CGD spec major: {spec_major}")

        indexes: list[_IndexRec] = []
        cursor = offset_polygon_index
        for _ in range(polygon_count):
            vals = POLYGON_INDEX_STRUCT.unpack_from(data, cursor)
            cursor += POLYGON_INDEX_STRUCT.size
            bbox_index, geom_offset, ring_count, string_index, iso2_raw, terminal_code, flags, _ = vals
            indexes.append(
                _IndexRec(
                    bbox_index=bbox_index,
                    geom_offset=geom_offset,
                    ring_count=ring_count,
                    string_index=string_index,
                    iso2=iso2_raw.decode("ascii", errors="ignore").strip("\x00"),
                    terminal_code=terminal_code,
                    flags=flags,
                )
            )

        bboxes: list[tuple[float, float, float, float]] = []
        cursor = offset_bbox_table
        for _ in range(polygon_count):
            bboxes.append(BBOX_STRUCT.unpack_from(data, cursor))
            cursor += BBOX_STRUCT.size

        strings: list[str] = []
        cursor = offset_string_offset_table
        for _ in range(string_count):
            str_offset, str_length, _ = STRING_OFFSET_STRUCT.unpack_from(data, cursor)
            cursor += STRING_OFFSET_STRUCT.size
            strings.append(data[str_offset:str_offset + str_length].decode("utf-8"))

        polys: list[_PolygonRec] = []
        for rec in indexes:
            rings = self._read_geometry(data, rec.geom_offset)
            if len(rings) != rec.ring_count:
                raise ValueError("CGD ring_count mismatch")
            polys.append(
                _PolygonRec(
                    bbox=bboxes[rec.bbox_index],
                    rings=rings,
                    iso2=rec.iso2,
                    terminal_code=rec.terminal_code,
                    flags=rec.flags,
                    name=strings[rec.string_index],
                )
            )
        return polys

    @staticmethod
    def _read_geometry(data: bytes, offset: int) -> list[list[tuple[float, float]]]:
        cursor = offset
        ring_count = int.from_bytes(data[cursor:cursor + 4], "little", signed=False)
        cursor += 4
        rings: list[list[tuple[float, float]]] = []
        for _ in range(ring_count):
            point_count = int.from_bytes(data[cursor:cursor + 4], "little", signed=False)
            cursor += 4
            ring: list[tuple[float, float]] = []
            for _ in range(point_count):
                lon, lat = struct.unpack_from("<ff", data, cursor)
                cursor += 8
                ring.append((lon, lat))
            rings.append(ring)
        return rings
