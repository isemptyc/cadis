from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path


def _quantize(value: float, min_value: float, span: float) -> int:
    if span == 0:
        return 0
    scaled = (value - min_value) / span * 65535.0
    if scaled <= 0:
        return 0
    if scaled >= 65535:
        return 65535
    return int(math.floor(scaled + 0.5))


def _point_in_ring(qx: int, qy: int, ring: list[tuple[int, int]]) -> bool:
    n = len(ring)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        # boundary counts as inside
        if _point_on_segment(qx, qy, xj, yj, xi, yi):
            return True
        if (yi > qy) != (yj > qy):
            den = yj - yi
            if den != 0:
                x_cross = (xj - xi) * (qy - yi) / den + xi
                if qx < x_cross:
                    inside = not inside
        j = i
    return inside


def _point_on_segment(px: int, py: int, x1: int, y1: int, x2: int, y2: int) -> bool:
    if px < min(x1, x2) or px > max(x1, x2):
        return False
    if py < min(y1, y2) or py > max(y1, y2):
        return False
    return (x2 - x1) * (py - y1) == (y2 - y1) * (px - x1)


@dataclass(frozen=True)
class _FeatureEntry:
    part_start: int
    part_count: int


@dataclass(frozen=True)
class _PartEntry:
    bbox: tuple[float, float, float, float]
    byte_offset: int
    byte_len: int
    ring_start: int
    ring_count: int


class WaterbodyIndex:
    """
    Minimal FFSF v3 loader for the global waterbody dataset.

    The waterbody.ffsf has no admin levels — features are flat named polygons.
    ``lookup()`` returns the primary name of the first matching polygon, or None.
    """

    def __init__(self, dataset_dir: str | Path) -> None:
        dataset_dir = Path(dataset_dir)
        ffsf_path = dataset_dir / "waterbody.ffsf"
        meta_path = dataset_dir / "waterbody_meta.json"

        blob = ffsf_path.read_bytes()

        magic = blob[0:4]
        if magic != b"FFSF":
            raise ValueError(f"Invalid FFSF magic in {ffsf_path}")
        version, feature_count, total_part_count = struct.unpack_from("<III", blob, 4)
        if version != 3:
            raise ValueError(f"Unsupported FFSF version {version}; expected 3")

        offset = 16
        features: list[_FeatureEntry] = []
        for _ in range(feature_count):
            _, _, part_start, part_count = struct.unpack_from("<4I", blob, offset)
            offset += 16
            features.append(_FeatureEntry(part_start=part_start, part_count=part_count))

        part_bboxes: list[tuple[float, float, float, float]] = []
        for _ in range(total_part_count):
            minx, miny, maxx, maxy = struct.unpack_from("<4f", blob, offset)
            offset += 16
            part_bboxes.append((minx, miny, maxx, maxy))

        parts: list[_PartEntry] = []
        total_ring_count = 0
        for i in range(total_part_count):
            byte_offset, byte_len, ring_start, ring_count = struct.unpack_from("<4I", blob, offset)
            offset += 16
            parts.append(_PartEntry(
                bbox=part_bboxes[i],
                byte_offset=byte_offset,
                byte_len=byte_len,
                ring_start=ring_start,
                ring_count=ring_count,
            ))
            total_ring_count += ring_count

        ring_sizes: list[int] = []
        for _ in range(total_ring_count):
            (point_count,) = struct.unpack_from("<I", blob, offset)
            offset += 4
            ring_sizes.append(point_count)

        self._features = features
        self._parts = parts
        self._ring_sizes = ring_sizes
        self._geometry = memoryview(blob)[offset:]
        self._meta: list[dict] = json.loads(meta_path.read_text(encoding="utf-8"))

        if len(self._features) != len(self._meta):
            raise ValueError("Feature count mismatch between FFSF and waterbody_meta.json")

    def lookup(self, lat: float, lon: float) -> str | None:
        for feature_idx, feature in enumerate(self._features):
            for part_idx in range(feature.part_start, feature.part_start + feature.part_count):
                if self._part_contains(part_idx, lon, lat):
                    meta = self._meta[feature_idx]
                    return meta.get("name") or None
        return None

    def _part_contains(self, part_idx: int, lon: float, lat: float) -> bool:
        part = self._parts[part_idx]
        minx, miny, maxx, maxy = part.bbox
        if not (minx <= lon <= maxx and miny <= lat <= maxy):
            return False

        spanx = maxx - minx
        spany = maxy - miny
        qx = _quantize(lon, minx, spanx)
        qy = _quantize(lat, miny, spany)

        outer, holes = self._read_rings(part)
        if not outer or not _point_in_ring(qx, qy, outer):
            return False
        for hole in holes:
            if hole and _point_in_ring(qx, qy, hole):
                return False
        return True

    def _read_rings(
        self, part: _PartEntry
    ) -> tuple[list[tuple[int, int]], list[list[tuple[int, int]]]]:
        data = self._geometry[part.byte_offset: part.byte_offset + part.byte_len]
        values = struct.unpack("<" + "H" * (len(data) // 2), data)
        cursor = 0
        rings: list[list[tuple[int, int]]] = []
        for ring_idx in range(part.ring_start, part.ring_start + part.ring_count):
            n = self._ring_sizes[ring_idx]
            ring = [(values[cursor + i * 2], values[cursor + i * 2 + 1]) for i in range(n)]
            cursor += n * 2
            rings.append(ring)
        if not rings:
            return [], []
        return rings[0], rings[1:]
