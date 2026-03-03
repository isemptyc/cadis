from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path

try:
    from shapely.geometry import Point
except ModuleNotFoundError:
    @dataclass(frozen=True)
    class Point:  # type: ignore[override]
        x: float
        y: float


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _quantize(value: float, min_value: float, span: float) -> int:
    if span == 0:
        return 0
    scaled = (value - min_value) / span * 65535.0
    if scaled <= 0:
        return 0
    if scaled >= 65535:
        return 65535
    return _round_half_up(scaled)


def _point_in_ring(qx: int, qy: int, ring_points: list[tuple[int, int]]) -> bool:
    """
    Even-odd ray casting in quantized integer space.
    """
    inside = False
    n = len(ring_points)
    if n < 3:
        return False

    j = n - 1
    for i in range(n):
        xi, yi = ring_points[i]
        xj, yj = ring_points[j]

        # Match shapely.covers() semantics: boundary counts as inside.
        if _point_on_segment(qx, qy, xj, yj, xi, yi):
            return True

        intersects = ((yi > qy) != (yj > qy))
        if intersects:
            den = yj - yi
            if den != 0:
                x_cross = (xj - xi) * (qy - yi) / den + xi
                if qx < x_cross:
                    inside = not inside
        j = i

    return inside


def _point_on_segment(
    px: int,
    py: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> bool:
    # Fast bbox reject.
    if px < min(x1, x2) or px > max(x1, x2):
        return False
    if py < min(y1, y2) or py > max(y1, y2):
        return False

    # Collinearity test via cross product.
    return (x2 - x1) * (py - y1) == (y2 - y1) * (px - x1)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    lat1_r = math.radians(lat1)
    lon1_r = math.radians(lon1)
    lat2_r = math.radians(lat2)
    lon2_r = math.radians(lon2)

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = (math.sin(dlat / 2) ** 2) + math.cos(lat1_r) * math.cos(lat2_r) * (
        math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return r * c


def _nearest_point_on_segment(
    px: float,
    py: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> tuple[float, float]:
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0.0 and dy == 0.0:
        return x1, y1

    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    if t <= 0.0:
        return x1, y1
    if t >= 1.0:
        return x2, y2
    return x1 + t * dx, y1 + t * dy


@dataclass(frozen=True)
class FeatureIndexEntry:
    part_start_idx: int
    part_count: int


@dataclass(frozen=True)
class GeomIndexV2Entry:
    byte_offset: int
    byte_len: int
    ring_start_idx: int
    ring_count: int


class FFSFSpatialIndexV2:
    """
    In-memory runtime for FFSF v2 datasets.
    """

    def __init__(
        self,
        *,
        feature_index: list[FeatureIndexEntry],
        part_bboxes: list[tuple[float, float, float, float]],
        geom_index: list[GeomIndexV2Entry],
        ring_index: list[int],
        geometry_data: memoryview,
        feature_meta_by_index: list[dict],
    ):
        self.feature_index = feature_index
        self.part_bboxes = part_bboxes
        self.geom_index = geom_index
        self.ring_index = ring_index
        self.geometry_data = geometry_data
        self.feature_meta_by_index = feature_meta_by_index

        if len(self.feature_index) != len(self.feature_meta_by_index):
            raise ValueError(
                "feature_meta_by_index length must match FFSF FeatureCount"
            )

    @classmethod
    def from_files(
        cls,
        *,
        ffsf_path: str | Path,
        feature_meta_path: str | Path,
    ) -> "FFSFSpatialIndexV2":
        ffsf_path = Path(ffsf_path)
        feature_meta_path = Path(feature_meta_path)

        blob = ffsf_path.read_bytes()
        if len(blob) < 16:
            raise ValueError(f"Invalid FFSF file (too small): {ffsf_path}")

        magic = blob[0:4]
        if magic != b"FFSF":
            raise ValueError(f"Invalid FFSF magic in {ffsf_path}")

        version, feature_count, total_part_count = struct.unpack_from("<III", blob, 4)
        if version != 2:
            raise ValueError(
                f"Unsupported FFSF version {version} in {ffsf_path}; expected v2"
            )

        offset = 16

        feature_index: list[FeatureIndexEntry] = []
        for _ in range(feature_count):
            _, _, part_start_idx, part_count = struct.unpack_from("<4I", blob, offset)
            offset += 16
            feature_index.append(
                FeatureIndexEntry(
                    part_start_idx=part_start_idx,
                    part_count=part_count,
                )
            )

        part_bboxes: list[tuple[float, float, float, float]] = []
        for _ in range(total_part_count):
            minx, miny, maxx, maxy = struct.unpack_from("<4f", blob, offset)
            offset += 16
            part_bboxes.append((minx, miny, maxx, maxy))

        geom_index: list[GeomIndexV2Entry] = []
        total_ring_count = 0
        for _ in range(total_part_count):
            byte_offset, byte_len, ring_start_idx, ring_count = struct.unpack_from(
                "<4I", blob, offset
            )
            offset += 16
            geom_index.append(
                GeomIndexV2Entry(
                    byte_offset=byte_offset,
                    byte_len=byte_len,
                    ring_start_idx=ring_start_idx,
                    ring_count=ring_count,
                )
            )
            total_ring_count += ring_count

        ring_index: list[int] = []
        for _ in range(total_ring_count):
            (point_count,) = struct.unpack_from("<I", blob, offset)
            offset += 4
            ring_index.append(point_count)

        geometry_data = memoryview(blob)[offset:]

        feature_meta_by_index = json.loads(feature_meta_path.read_text(encoding="utf-8"))
        if not isinstance(feature_meta_by_index, list):
            raise ValueError("feature_meta_by_index dataset must be a JSON list")

        return cls(
            feature_index=feature_index,
            part_bboxes=part_bboxes,
            geom_index=geom_index,
            ring_index=ring_index,
            geometry_data=geometry_data,
            feature_meta_by_index=feature_meta_by_index,
        )

    def query_point(self, pt: Point, levels: list[int]) -> dict[int, dict]:
        """
        Return first matching feature per level, preserving feature index order.
        """
        level_set = set(levels)
        hits: dict[int, dict] = {}

        for feature_idx, feature in enumerate(self.feature_index):
            meta = self.feature_meta_by_index[feature_idx]
            level = meta.get("level")
            if level not in level_set:
                continue
            if level in hits:
                continue

            if self._feature_contains_point(feature, pt):
                feature_id = meta.get("feature_id")
                hits[level] = {
                    "level": level,
                    "name": meta.get("name"),
                    "osm_id": feature_id,
                    "source": "polygon",
                }

            if len(hits) == len(level_set):
                break

        return hits

    def build_country_scope_allowlist(
        self,
        *,
        levels: list[int],
    ) -> dict[int, set[str]]:
        """
        Build a per-level allowlist from exporter-precomputed metadata.
        """
        allowlist: dict[int, set[str]] = {level: set() for level in levels}
        level_set = set(levels)

        for feature_meta in self.feature_meta_by_index:
            level = feature_meta.get("level")
            if level not in level_set:
                continue

            feature_id = feature_meta.get("feature_id")
            if not feature_id:
                continue

            if feature_meta.get("country_scope_flag") is True:
                allowlist[level].add(feature_id)

        return allowlist

    def _feature_contains_point(self, feature: FeatureIndexEntry, pt: Point) -> bool:
        for part_idx in range(feature.part_start_idx, feature.part_start_idx + feature.part_count):
            if self._part_contains_point(part_idx, pt):
                return True
        return False

    def _part_contains_point(self, part_idx: int, pt: Point) -> bool:
        minx, miny, maxx, maxy = self.part_bboxes[part_idx]
        if not (minx <= pt.x <= maxx and miny <= pt.y <= maxy):
            return False

        spanx = maxx - minx
        spany = maxy - miny
        qx = _quantize(pt.x, minx, spanx)
        qy = _quantize(pt.y, miny, spany)

        geom = self.geom_index[part_idx]
        if geom.ring_count == 0:
            return False

        outer, holes = self._read_rings(geom)
        if not outer:
            return False

        if not _point_in_ring(qx, qy, outer):
            return False

        for hole in holes:
            if hole and _point_in_ring(qx, qy, hole):
                return False

        return True

    def _read_rings(
        self,
        geom: GeomIndexV2Entry,
    ) -> tuple[list[tuple[int, int]], list[list[tuple[int, int]]]]:
        data = self.geometry_data[geom.byte_offset: geom.byte_offset + geom.byte_len]
        if len(data) % 2 != 0:
            raise ValueError("GeometryData byte length must be even")

        values = struct.unpack("<" + "H" * (len(data) // 2), data)
        cursor = 0
        rings: list[list[tuple[int, int]]] = []

        for ring_idx in range(geom.ring_start_idx, geom.ring_start_idx + geom.ring_count):
            point_count = self.ring_index[ring_idx]
            ring: list[tuple[int, int]] = []
            for _ in range(point_count):
                x = values[cursor]
                y = values[cursor + 1]
                cursor += 2
                ring.append((x, y))
            rings.append(ring)

        if not rings:
            return [], []
        return rings[0], rings[1:]


class FFSFSpatialIndexV3:
    """
    In-memory runtime for FFSF v3 datasets.

    v3 retains the v2 geometry layout but adds a nearest-polygon operator,
    making the .bin dataset authoritative at runtime.
    """

    def __init__(
        self,
        *,
        feature_index: list[FeatureIndexEntry],
        part_bboxes: list[tuple[float, float, float, float]],
        geom_index: list[GeomIndexV2Entry],
        ring_index: list[int],
        geometry_data: memoryview,
        feature_meta_by_index: list[dict],
    ):
        self.feature_index = feature_index
        self.part_bboxes = part_bboxes
        self.geom_index = geom_index
        self.ring_index = ring_index
        self.geometry_data = geometry_data
        self.feature_meta_by_index = feature_meta_by_index

        if len(self.feature_index) != len(self.feature_meta_by_index):
            raise ValueError(
                "feature_meta_by_index length must match FFSF FeatureCount"
            )

        self.part_feature_index: list[int] = [-1] * len(self.part_bboxes)
        for feature_idx, feature in enumerate(self.feature_index):
            for part_idx in range(feature.part_start_idx, feature.part_start_idx + feature.part_count):
                self.part_feature_index[part_idx] = feature_idx

        self.feature_id_to_index: dict[str, int] = {}
        for feature_idx, meta in enumerate(self.feature_meta_by_index):
            feature_id = meta.get("feature_id")
            if isinstance(feature_id, str) and feature_id:
                self.feature_id_to_index[feature_id] = feature_idx

        self.country_scope_feature_indices: list[int] = []
        self.country_scope_part_indices: list[int] = []
        for feature_idx, feature in enumerate(self.feature_index):
            meta = self.feature_meta_by_index[feature_idx]
            if meta.get("country_scope_flag") is not True:
                continue
            self.country_scope_feature_indices.append(feature_idx)
            for part_idx in range(feature.part_start_idx, feature.part_start_idx + feature.part_count):
                self.country_scope_part_indices.append(part_idx)

        # Backward compatibility: older datasets may not carry country_scope_flag.
        # In that case, approximate country scope using the highest structural
        # level available in geometry metadata (smallest numeric level).
        if not self.country_scope_feature_indices:
            min_level = None
            for meta in self.feature_meta_by_index:
                level = meta.get("level")
                if not isinstance(level, int):
                    continue
                if min_level is None or level < min_level:
                    min_level = level
            if min_level is not None:
                for feature_idx, feature in enumerate(self.feature_index):
                    meta = self.feature_meta_by_index[feature_idx]
                    if meta.get("level") != min_level:
                        continue
                    self.country_scope_feature_indices.append(feature_idx)
                    for part_idx in range(feature.part_start_idx, feature.part_start_idx + feature.part_count):
                        self.country_scope_part_indices.append(part_idx)

    @classmethod
    def from_files(
        cls,
        *,
        ffsf_path: str | Path,
        feature_meta_path: str | Path,
    ) -> "FFSFSpatialIndexV3":
        ffsf_path = Path(ffsf_path)
        feature_meta_path = Path(feature_meta_path)

        blob = ffsf_path.read_bytes()
        if len(blob) < 16:
            raise ValueError(f"Invalid FFSF file (too small): {ffsf_path}")

        magic = blob[0:4]
        if magic != b"FFSF":
            raise ValueError(f"Invalid FFSF magic in {ffsf_path}")

        version, feature_count, total_part_count = struct.unpack_from("<III", blob, 4)
        if version != 3:
            raise ValueError(
                f"Unsupported FFSF version {version} in {ffsf_path}; expected v3"
            )

        offset = 16

        feature_index: list[FeatureIndexEntry] = []
        for _ in range(feature_count):
            _, _, part_start_idx, part_count = struct.unpack_from("<4I", blob, offset)
            offset += 16
            feature_index.append(
                FeatureIndexEntry(
                    part_start_idx=part_start_idx,
                    part_count=part_count,
                )
            )

        part_bboxes: list[tuple[float, float, float, float]] = []
        for _ in range(total_part_count):
            minx, miny, maxx, maxy = struct.unpack_from("<4f", blob, offset)
            offset += 16
            part_bboxes.append((minx, miny, maxx, maxy))

        geom_index: list[GeomIndexV2Entry] = []
        total_ring_count = 0
        for _ in range(total_part_count):
            byte_offset, byte_len, ring_start_idx, ring_count = struct.unpack_from(
                "<4I", blob, offset
            )
            offset += 16
            geom_index.append(
                GeomIndexV2Entry(
                    byte_offset=byte_offset,
                    byte_len=byte_len,
                    ring_start_idx=ring_start_idx,
                    ring_count=ring_count,
                )
            )
            total_ring_count += ring_count

        ring_index: list[int] = []
        for _ in range(total_ring_count):
            (point_count,) = struct.unpack_from("<I", blob, offset)
            offset += 4
            ring_index.append(point_count)

        geometry_data = memoryview(blob)[offset:]

        feature_meta_by_index = json.loads(feature_meta_path.read_text(encoding="utf-8"))
        if not isinstance(feature_meta_by_index, list):
            raise ValueError("feature_meta_by_index dataset must be a JSON list")

        return cls(
            feature_index=feature_index,
            part_bboxes=part_bboxes,
            geom_index=geom_index,
            ring_index=ring_index,
            geometry_data=geometry_data,
            feature_meta_by_index=feature_meta_by_index,
        )

    def query_point(self, pt: Point, levels: list[int]) -> dict[int, dict]:
        """
        Return first matching feature per level, preserving feature index order.
        """
        level_set = set(levels)
        hits: dict[int, dict] = {}

        for feature_idx, feature in enumerate(self.feature_index):
            meta = self.feature_meta_by_index[feature_idx]
            level = meta.get("level")
            if level not in level_set:
                continue
            if level in hits:
                continue

            if self._feature_contains_point(feature, pt):
                feature_id = meta.get("feature_id")
                hits[level] = {
                    "level": level,
                    "name": meta.get("name"),
                    "osm_id": feature_id,
                    "source": "polygon",
                }

            if len(hits) == len(level_set):
                break

        return hits

    def query_point_nearest(
        self,
        pt: Point,
        max_distance_km: float,
        levels: list[int],
    ) -> dict[int, dict]:
        """
        Return nearest feature per level within max_distance_km.
        """
        if max_distance_km <= 0:
            return {}

        level_set = set(levels)
        max_km = float(max_distance_km)
        threshold_deg = max_km / 111.0

        qminx = pt.x - threshold_deg
        qmaxx = pt.x + threshold_deg
        qminy = pt.y - threshold_deg
        qmaxy = pt.y + threshold_deg

        nearest_by_level: dict[int, tuple[float, dict]] = {}

        for part_idx, (minx, miny, maxx, maxy) in enumerate(self.part_bboxes):
            if maxx < qminx or minx > qmaxx or maxy < qminy or miny > qmaxy:
                continue

            feature_idx = self.part_feature_index[part_idx]
            if feature_idx < 0:
                continue
            meta = self.feature_meta_by_index[feature_idx]
            level = meta.get("level")
            if level not in level_set:
                continue

            dist_km = self._distance_km_to_part(pt, part_idx, minx, miny, maxx, maxy)
            if dist_km > max_km:
                continue

            best = nearest_by_level.get(level)
            if best is None or dist_km < best[0]:
                nearest_by_level[level] = (dist_km, meta)

        hits: dict[int, dict] = {}
        for level, (_, meta) in nearest_by_level.items():
            feature_id = meta.get("feature_id")
            hits[level] = {
                "level": level,
                "name": meta.get("name"),
                "osm_id": feature_id,
                "source": "nearby",
            }

        return hits

    def has_country_scope_geometry(self) -> bool:
        return bool(self.country_scope_part_indices)

    def country_scope_contains_point(self, pt: Point) -> bool:
        for part_idx in self.country_scope_part_indices:
            if self._part_contains_point(part_idx, pt):
                return True
        return False

    def distance_km_to_country_scope(self, pt: Point) -> float:
        if not self.country_scope_part_indices:
            return float("inf")
        if self.country_scope_contains_point(pt):
            return 0.0

        min_dist = float("inf")
        for part_idx in self.country_scope_part_indices:
            minx, miny, maxx, maxy = self.part_bboxes[part_idx]
            dist = self._distance_km_to_part(pt, part_idx, minx, miny, maxx, maxy)
            if dist < min_dist:
                min_dist = dist
        return min_dist

    def distance_km_to_feature_id(self, pt: Point, feature_id: str) -> float:
        feature_idx = self.feature_id_to_index.get(feature_id)
        if feature_idx is None:
            return float("inf")
        feature = self.feature_index[feature_idx]
        min_dist = float("inf")
        for part_idx in range(feature.part_start_idx, feature.part_start_idx + feature.part_count):
            minx, miny, maxx, maxy = self.part_bboxes[part_idx]
            dist = self._distance_km_to_part(pt, part_idx, minx, miny, maxx, maxy)
            if dist < min_dist:
                min_dist = dist
        return min_dist

    def build_country_scope_allowlist(
        self,
        *,
        levels: list[int],
    ) -> dict[int, set[str]]:
        """
        Build a per-level allowlist from exporter-precomputed metadata.
        """
        allowlist: dict[int, set[str]] = {level: set() for level in levels}
        level_set = set(levels)

        for feature_meta in self.feature_meta_by_index:
            level = feature_meta.get("level")
            if level not in level_set:
                continue

            feature_id = feature_meta.get("feature_id")
            if not feature_id:
                continue

            if feature_meta.get("country_scope_flag") is True:
                allowlist[level].add(feature_id)

        return allowlist

    def _feature_contains_point(self, feature: FeatureIndexEntry, pt: Point) -> bool:
        for part_idx in range(feature.part_start_idx, feature.part_start_idx + feature.part_count):
            if self._part_contains_point(part_idx, pt):
                return True
        return False

    def _part_contains_point(self, part_idx: int, pt: Point) -> bool:
        minx, miny, maxx, maxy = self.part_bboxes[part_idx]
        if not (minx <= pt.x <= maxx and miny <= pt.y <= maxy):
            return False

        spanx = maxx - minx
        spany = maxy - miny
        qx = _quantize(pt.x, minx, spanx)
        qy = _quantize(pt.y, miny, spany)

        geom = self.geom_index[part_idx]
        if geom.ring_count == 0:
            return False

        outer, holes = self._read_rings(geom)
        if not outer:
            return False

        if not _point_in_ring(qx, qy, outer):
            return False

        for hole in holes:
            if hole and _point_in_ring(qx, qy, hole):
                return False

        return True

    def _distance_km_to_part(
        self,
        pt: Point,
        part_idx: int,
        minx: float,
        miny: float,
        maxx: float,
        maxy: float,
    ) -> float:
        spanx = maxx - minx
        spany = maxy - miny
        geom = self.geom_index[part_idx]
        if geom.ring_count == 0:
            return float("inf")

        outer, holes = self._read_rings(geom)
        rings = []
        if outer:
            rings.append(outer)
        rings.extend([hole for hole in holes if hole])

        min_dist = float("inf")
        for ring in rings:
            ring_points = self._decode_ring_points(ring, minx, miny, spanx, spany)
            if not ring_points:
                continue
            dist = self._distance_km_to_ring(pt, ring_points)
            if dist < min_dist:
                min_dist = dist
        return min_dist

    def _distance_km_to_ring(
        self,
        pt: Point,
        ring_points: list[tuple[float, float]],
    ) -> float:
        if len(ring_points) < 2:
            return float("inf")

        min_dist = float("inf")
        count = len(ring_points)
        closed = ring_points[0] == ring_points[-1]
        limit = count - 1 if closed else count

        for i in range(limit):
            x1, y1 = ring_points[i]
            x2, y2 = ring_points[(i + 1) % count]
            nx, ny = _nearest_point_on_segment(pt.x, pt.y, x1, y1, x2, y2)
            dist = _haversine_km(pt.y, pt.x, ny, nx)
            if dist < min_dist:
                min_dist = dist

        return min_dist

    def _decode_ring_points(
        self,
        ring: list[tuple[int, int]],
        minx: float,
        miny: float,
        spanx: float,
        spany: float,
    ) -> list[tuple[float, float]]:
        if not ring:
            return []
        points: list[tuple[float, float]] = []
        if spanx == 0:
            spanx = 1.0
        if spany == 0:
            spany = 1.0
        for qx, qy in ring:
            x = minx + (qx / 65535.0) * spanx
            y = miny + (qy / 65535.0) * spany
            points.append((x, y))
        return points

    def _read_rings(
        self,
        geom: GeomIndexV2Entry,
    ) -> tuple[list[tuple[int, int]], list[list[tuple[int, int]]]]:
        data = self.geometry_data[geom.byte_offset: geom.byte_offset + geom.byte_len]
        if len(data) % 2 != 0:
            raise ValueError("GeometryData byte length must be even")

        values = struct.unpack("<" + "H" * (len(data) // 2), data)
        cursor = 0
        rings: list[list[tuple[int, int]]] = []

        for ring_idx in range(geom.ring_start_idx, geom.ring_start_idx + geom.ring_count):
            point_count = self.ring_index[ring_idx]
            ring: list[tuple[int, int]] = []
            for _ in range(point_count):
                x = values[cursor]
                y = values[cursor + 1]
                cursor += 2
                ring.append((x, y))
            rings.append(ring)

        if not rings:
            return [], []
        return rings[0], rings[1:]
