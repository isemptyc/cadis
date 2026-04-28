from __future__ import annotations

import json
import logging
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from shapely.geometry import Point
except ModuleNotFoundError:
    @dataclass(frozen=True)
    class Point:  # type: ignore[override]
        x: float
        y: float


_LOGGER = logging.getLogger(__name__)


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


FFSFGeometryParse = tuple[
    list[FeatureIndexEntry],
    list[tuple[float, float, float, float]],
    list[GeomIndexV2Entry],
    list[int],
    memoryview,
]

_RUNTIME_FEATURE_META_KEYS = {
    "level",
    "feature_id",
    "name",
    "names",
    "country_scope_flag",
}

_FEATURE_META_COLUMNS = {
    "level": "levels",
    "feature_id": "feature_ids",
    "name": "names",
    "names": "names_i18n",
    "country_scope_flag": "country_scope_flags",
}


class FeatureMetaView:
    __slots__ = ("_columns", "_index")

    def __init__(self, columns: "FeatureMetaColumns", index: int):
        self._columns = columns
        self._index = index

    def get(self, key: str, default: object = None) -> object:
        column_name = _FEATURE_META_COLUMNS.get(key)
        if column_name is None:
            return default
        values = getattr(self._columns, column_name)
        value = values[self._index]
        return default if value is None else value


class FeatureMetaColumns:
    __slots__ = (
        "levels",
        "feature_ids",
        "names",
        "names_i18n",
        "country_scope_flags",
        "id_to_index",
    )

    def __init__(
        self,
        *,
        levels: list[int | None],
        feature_ids: list[str | int | None],
        names: list[str | None],
        names_i18n: list[dict | None],
        country_scope_flags: list[bool],
        id_to_index: dict[str, int],
    ):
        self.levels = levels
        self.feature_ids = feature_ids
        self.names = names
        self.names_i18n = names_i18n
        self.country_scope_flags = country_scope_flags
        self.id_to_index = id_to_index

    @classmethod
    def from_rows(cls, rows: list[dict]) -> "FeatureMetaColumns":
        levels: list[int | None] = []
        feature_ids: list[str | int | None] = []
        names: list[str | None] = []
        names_i18n: list[dict | None] = []
        country_scope_flags: list[bool] = []
        id_to_index: dict[str, int] = {}

        for feature_idx, meta in enumerate(rows):
            level = meta.get("level") if isinstance(meta, dict) else None
            feature_id = meta.get("feature_id") if isinstance(meta, dict) else None
            name = meta.get("name") if isinstance(meta, dict) else None
            row_names = meta.get("names") if isinstance(meta, dict) else None
            country_scope_flag = (
                meta.get("country_scope_flag") is True
                if isinstance(meta, dict)
                else False
            )

            levels.append(level if isinstance(level, int) else None)
            feature_ids.append(
                feature_id if isinstance(feature_id, (str, int)) else None
            )
            names.append(name if isinstance(name, str) else None)
            names_i18n.append(row_names if isinstance(row_names, dict) else None)
            country_scope_flags.append(country_scope_flag)
            if isinstance(feature_id, str) and feature_id:
                id_to_index[feature_id] = feature_idx

        return cls(
            levels=levels,
            feature_ids=feature_ids,
            names=names,
            names_i18n=names_i18n,
            country_scope_flags=country_scope_flags,
            id_to_index=id_to_index,
        )

    def __len__(self) -> int:
        return len(self.levels)

    def __getitem__(self, index: int) -> FeatureMetaView:
        return FeatureMetaView(self, index)

    def __iter__(self):
        for index in range(len(self)):
            yield FeatureMetaView(self, index)

    def row_json(self, index: int) -> dict[str, object]:
        row: dict[str, object] = {}
        level = self.levels[index]
        feature_id = self.feature_ids[index]
        name = self.names[index]
        names = self.names_i18n[index]
        if level is not None:
            row["level"] = level
        if feature_id is not None:
            row["feature_id"] = feature_id
        if name is not None:
            row["name"] = name
        if names:
            row["names"] = names
        row["country_scope_flag"] = self.country_scope_flags[index]
        return row

    def rows_json(self) -> list[dict[str, object]]:
        return [self.row_json(index) for index in range(len(self))]


FeatureMetaStorage = list[dict] | FeatureMetaColumns


def _trim_feature_meta_enabled() -> bool:
    raw = os.environ.get("CADIS_TRIM_FEATURE_META", "on")
    value = raw.strip().lower() if isinstance(raw, str) else "on"
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"Unsupported CADIS_TRIM_FEATURE_META={raw!r}; expected on or off"
    )


def _feature_meta_mode() -> str:
    raw = os.environ.get("CADIS_FEATURE_META_MODE", "dict")
    value = raw.strip().lower() if isinstance(raw, str) else "dict"
    if value not in {"dict", "columnar"}:
        raise ValueError(
            f"Unsupported CADIS_FEATURE_META_MODE={raw!r}; expected dict or columnar"
        )
    return value


def _normalize_feature_meta_by_index(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("feature_meta_by_index dataset must be a JSON list")
    if not _trim_feature_meta_enabled():
        return raw
    return [
        {key: value for key, value in meta.items() if key in _RUNTIME_FEATURE_META_KEYS}
        if isinstance(meta, dict)
        else meta
        for meta in raw
    ]


def _prepare_feature_meta_storage(rows: list[dict]) -> FeatureMetaStorage:
    if _feature_meta_mode() == "columnar":
        return FeatureMetaColumns.from_rows(rows)
    return rows


def _json_size_bytes(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _feature_meta_memory_report(feature_meta_by_index: FeatureMetaStorage) -> dict[str, Any]:
    if isinstance(feature_meta_by_index, FeatureMetaColumns):
        return _feature_meta_columns_memory_report(feature_meta_by_index)

    object_count = 0
    total_key_count = 0
    feature_ids: set[str] = set()
    names: set[str] = set()
    localized_names: set[str] = set()
    names_payload: list[dict[str, object]] = []

    for meta in feature_meta_by_index:
        if not isinstance(meta, dict):
            continue
        object_count += 1
        total_key_count += len(meta)

        feature_id = meta.get("feature_id")
        if isinstance(feature_id, str):
            feature_ids.add(feature_id)

        name = meta.get("name")
        row_names_payload: dict[str, object] = {}
        if isinstance(name, str):
            names.add(name)
            row_names_payload["name"] = name

        meta_names = meta.get("names")
        if isinstance(meta_names, dict):
            row_names_payload["names"] = meta_names
            for localized_name in meta_names.values():
                if isinstance(localized_name, str):
                    localized_names.add(localized_name)
        if row_names_payload:
            names_payload.append(row_names_payload)

    avg_keys = total_key_count / object_count if object_count else 0.0
    return {
        "feature_meta_mode": "dict",
        "feature_meta_count": len(feature_meta_by_index),
        "feature_meta_object_count": object_count,
        "feature_meta_total_key_count": total_key_count,
        "feature_meta_avg_keys_per_object": avg_keys,
        "feature_meta_unique_feature_id_count": len(feature_ids),
        "feature_meta_unique_name_count": len(names),
        "feature_meta_unique_localized_name_count": len(localized_names),
        "feature_meta_json_bytes": _json_size_bytes(feature_meta_by_index),
        "feature_meta_names_json_bytes": _json_size_bytes(names_payload),
    }


def _feature_meta_columns_memory_report(columns: FeatureMetaColumns) -> dict[str, Any]:
    feature_ids = {
        feature_id
        for feature_id in columns.feature_ids
        if isinstance(feature_id, str)
    }
    names = {name for name in columns.names if isinstance(name, str)}
    localized_names: set[str] = set()
    names_payload: list[dict[str, object]] = []
    for index, row_names in enumerate(columns.names_i18n):
        row_names_payload: dict[str, object] = {}
        name = columns.names[index]
        if isinstance(name, str):
            row_names_payload["name"] = name
        if isinstance(row_names, dict):
            row_names_payload["names"] = row_names
            for localized_name in row_names.values():
                if isinstance(localized_name, str):
                    localized_names.add(localized_name)
        if row_names_payload:
            names_payload.append(row_names_payload)

    total_key_count = sum(len(columns.row_json(index)) for index in range(len(columns)))
    return {
        "feature_meta_mode": "columnar",
        "feature_meta_count": len(columns),
        "feature_meta_object_count": 0,
        "feature_meta_total_key_count": total_key_count,
        "feature_meta_avg_keys_per_object": 0.0,
        "feature_meta_unique_feature_id_count": len(feature_ids),
        "feature_meta_unique_name_count": len(names),
        "feature_meta_unique_localized_name_count": len(localized_names),
        "feature_meta_json_bytes": _json_size_bytes(columns.rows_json()),
        "feature_meta_names_json_bytes": _json_size_bytes(names_payload),
    }


def _build_public_feature_hit(*, level: int, meta: Any, source: str) -> dict:
    hit = {
        "level": level,
        "name": meta.get("name"),
        "osm_id": meta.get("feature_id"),
        "source": source,
    }
    names = meta.get("names")
    if isinstance(names, dict) and names:
        hit["names"] = names
    return hit


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

        feature_meta_by_index = _normalize_feature_meta_by_index(
            json.loads(feature_meta_path.read_text(encoding="utf-8"))
        )

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
                hits[level] = _build_public_feature_hit(
                    level=level,
                    meta=meta,
                    source="polygon",
                )

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


def _select_country_scope_feature_indices(
    *,
    feature_index: list[FeatureIndexEntry],
    feature_meta_by_index: FeatureMetaStorage,
) -> tuple[list[int], list[int]]:
    """
    Choose the geometry features used for country-scope execution.

    If exporter-provided `country_scope_flag` exists, trust that as scope truth
    but minimize execution geometry to the smallest numeric admin level among
    the flagged features. This preserves exporter intent while avoiding country
    checks over every in-scope municipality or subunit.

    Older datasets without `country_scope_flag` continue to fall back to the
    smallest numeric level present in geometry metadata.
    """
    flagged_levels: list[int] = []
    for meta in feature_meta_by_index:
        if meta.get("country_scope_flag") is not True:
            continue
        level = meta.get("level")
        if isinstance(level, int):
            flagged_levels.append(level)

    target_level: int | None = min(flagged_levels) if flagged_levels else None
    use_flagged_scope = target_level is not None

    if target_level is None:
        for meta in feature_meta_by_index:
            level = meta.get("level")
            if not isinstance(level, int):
                continue
            if target_level is None or level < target_level:
                target_level = level

    if target_level is None:
        return [], []

    feature_indices: list[int] = []
    part_indices: list[int] = []
    for feature_idx, feature in enumerate(feature_index):
        meta = feature_meta_by_index[feature_idx]
        if use_flagged_scope and meta.get("country_scope_flag") is not True:
            continue
        if meta.get("level") != target_level:
            continue
        feature_indices.append(feature_idx)
        for part_idx in range(feature.part_start_idx, feature.part_start_idx + feature.part_count):
            part_indices.append(part_idx)

    return feature_indices, part_indices


def _requested_ffsf_backend() -> str:
    raw = os.environ.get("CADIS_FFSF_BACKEND", "auto")
    backend = raw.strip().lower() if isinstance(raw, str) else "auto"
    if backend not in {"auto", "python", "native"}:
        raise ValueError(
            f"Unsupported CADIS_FFSF_BACKEND={raw!r}; expected one of: auto, native, python"
        )
    return backend


def _requested_ffsf_fallback_geometry() -> str:
    raw = os.environ.get("CADIS_FFSF_FALLBACK_GEOMETRY", "auto")
    backend = raw.strip().lower() if isinstance(raw, str) else "auto"
    if backend not in {"auto", "python", "native"}:
        raise ValueError(
            "Unsupported CADIS_FFSF_FALLBACK_GEOMETRY="
            f"{raw!r}; expected one of: auto, native, python"
        )
    return backend


def _requested_ffsf_fallback_geometry_shadow() -> bool:
    raw = os.environ.get("CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _fallback_geometry_shadow_distance_tolerance_km() -> float:
    raw = os.environ.get("CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW_DISTANCE_TOLERANCE_KM")
    if raw is None:
        return 1e-6
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            "CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW_DISTANCE_TOLERANCE_KM "
            "must be a finite non-negative number"
        ) from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(
            "CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW_DISTANCE_TOLERANCE_KM "
            "must be a finite non-negative number"
        )
    return value


def _load_native_ffsf_kernel() -> type[Any]:
    from cadis_native_cgd import FfsfRuntimeKernel

    return FfsfRuntimeKernel


def _create_native_ffsf_kernel(*, ffsf_path: Path, feature_meta_path: Path) -> Any | None:
    backend = _requested_ffsf_backend()
    if backend == "python":
        return None
    if backend == "native":
        native_kernel = _load_native_ffsf_kernel()
        return native_kernel(ffsf_path, feature_meta_path)
    try:
        native_kernel = _load_native_ffsf_kernel()
        return native_kernel(ffsf_path, feature_meta_path)
    except Exception:
        return None


def _native_kernel_has_fallback_geometry(native_kernel: Any | None) -> bool:
    if native_kernel is None:
        return False
    return all(
        hasattr(native_kernel, name)
        for name in (
            "country_scope_contains_point",
            "distance_km_to_country_scope",
            "distance_km_to_feature_index",
            "query_point_nearest_feature_indices",
        )
    )


def _read_ffsf_header(blob: bytes, *, ffsf_path: Path) -> tuple[int, int]:
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
    return feature_count, total_part_count


def _read_ffsf_feature_index_only(
    ffsf_path: Path,
) -> FFSFGeometryParse:
    with ffsf_path.open("rb") as fh:
        header = fh.read(16)
        feature_count, _ = _read_ffsf_header(header, ffsf_path=ffsf_path)
        feature_blob = fh.read(feature_count * 16)
    if len(feature_blob) != feature_count * 16:
        raise ValueError(f"Invalid FFSF feature index in {ffsf_path}")

    offset = 0
    feature_index: list[FeatureIndexEntry] = []
    for _ in range(feature_count):
        _, _, part_start_idx, part_count = struct.unpack_from("<4I", feature_blob, offset)
        offset += 16
        feature_index.append(
            FeatureIndexEntry(
                part_start_idx=part_start_idx,
                part_count=part_count,
            )
        )

    return feature_index, [], [], [], memoryview(b"")


def _read_ffsf_full_geometry(
    ffsf_path: Path,
) -> FFSFGeometryParse:
    blob = ffsf_path.read_bytes()
    feature_count, total_part_count = _read_ffsf_header(blob, ffsf_path=ffsf_path)

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

    return feature_index, part_bboxes, geom_index, ring_index, memoryview(blob)[offset:]

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
        feature_meta_by_index: list[dict] | FeatureMetaColumns,
        native_kernel: Any | None = None,
    ):
        self.feature_index = feature_index
        self.part_bboxes = part_bboxes
        self.geom_index = geom_index
        self.ring_index = ring_index
        self.geometry_data = geometry_data
        self.feature_meta_by_index = (
            _prepare_feature_meta_storage(feature_meta_by_index)
            if isinstance(feature_meta_by_index, list)
            else feature_meta_by_index
        )
        self.native_kernel = native_kernel
        requested_fallback_geometry = _requested_ffsf_fallback_geometry()
        if requested_fallback_geometry == "native" and native_kernel is None:
            raise RuntimeError(
                "CADIS_FFSF_FALLBACK_GEOMETRY=native requires a native FFSF runtime"
            )
        self._native_fallback_geometry = (
            requested_fallback_geometry
            if native_kernel is not None
            else "python"
        )
        self._fallback_geometry_shadow_enabled = (
            native_kernel is not None
            and _requested_ffsf_fallback_geometry_shadow()
        )
        self._fallback_geometry_shadow_distance_tolerance_km = (
            _fallback_geometry_shadow_distance_tolerance_km()
            if self._fallback_geometry_shadow_enabled
            else 1e-6
        )

        if len(self.feature_index) != len(self.feature_meta_by_index):
            raise ValueError(
                "feature_meta_by_index length must match FFSF FeatureCount"
            )

        total_part_count = len(self.part_bboxes)
        if total_part_count == 0:
            for feature in self.feature_index:
                total_part_count = max(
                    total_part_count,
                    feature.part_start_idx + feature.part_count,
                )

        self.part_feature_index: list[int] = [-1] * total_part_count
        for feature_idx, feature in enumerate(self.feature_index):
            for part_idx in range(feature.part_start_idx, feature.part_start_idx + feature.part_count):
                self.part_feature_index[part_idx] = feature_idx

        if isinstance(self.feature_meta_by_index, FeatureMetaColumns):
            self.feature_id_to_index = self.feature_meta_by_index.id_to_index
        else:
            self.feature_id_to_index: dict[str, int] = {}
            for feature_idx, meta in enumerate(self.feature_meta_by_index):
                feature_id = meta.get("feature_id")
                if isinstance(feature_id, str) and feature_id:
                    self.feature_id_to_index[feature_id] = feature_idx

        (
            self.country_scope_feature_indices,
            self.country_scope_part_indices,
        ) = _select_country_scope_feature_indices(
            feature_index=self.feature_index,
            feature_meta_by_index=self.feature_meta_by_index,
        )
        self._python_geometry_retained = True
        if self._can_release_python_geometry():
            self._release_python_geometry()

    @property
    def backend_name(self) -> str:
        return "native" if self.native_kernel is not None else "python"

    @property
    def fallback_geometry_backend_name(self) -> str:
        if self._native_fallback_geometry != "python" and self._has_native_fallback_geometry():
            return "native"
        return "python"

    @property
    def python_geometry_retained(self) -> bool:
        return self._python_geometry_retained

    def memory_report(self) -> dict[str, Any]:
        return {
            "backend_name": self.backend_name,
            "fallback_geometry_backend_name": self.fallback_geometry_backend_name,
            "python_geometry_retained": self.python_geometry_retained,
            "feature_count": len(self.feature_meta_by_index),
            "part_count": len(self.part_feature_index),
            "feature_index_count": len(self.feature_index),
            "part_bbox_count": len(self.part_bboxes),
            "geom_index_count": len(self.geom_index),
            "ring_index_count": len(self.ring_index),
            "geometry_data_bytes": len(self.geometry_data),
            **_feature_meta_memory_report(self.feature_meta_by_index),
        }

    def _feature_level(self, feature_idx: int) -> object:
        if isinstance(self.feature_meta_by_index, FeatureMetaColumns):
            return self.feature_meta_by_index.levels[feature_idx]
        return self.feature_meta_by_index[feature_idx].get("level")

    def _build_hit_from_feature_index(
        self,
        *,
        feature_idx: int,
        level: int,
        source: str,
    ) -> dict:
        if isinstance(self.feature_meta_by_index, FeatureMetaColumns):
            feature_id = self.feature_meta_by_index.feature_ids[feature_idx]
            hit = {
                "level": level,
                "name": self.feature_meta_by_index.names[feature_idx],
                "osm_id": feature_id,
                "source": source,
            }
            names = self.feature_meta_by_index.names_i18n[feature_idx]
            if isinstance(names, dict) and names:
                hit["names"] = names
            return hit

        return _build_public_feature_hit(
            level=level,
            meta=self.feature_meta_by_index[feature_idx],
            source=source,
        )

    @classmethod
    def from_files(
        cls,
        *,
        ffsf_path: str | Path,
        feature_meta_path: str | Path,
    ) -> "FFSFSpatialIndexV3":
        ffsf_path = Path(ffsf_path)
        feature_meta_path = Path(feature_meta_path)

        feature_meta_by_index = _normalize_feature_meta_by_index(
            json.loads(feature_meta_path.read_text(encoding="utf-8"))
        )

        native_kernel = _create_native_ffsf_kernel(
            ffsf_path=ffsf_path,
            feature_meta_path=feature_meta_path,
        )
        requested_fallback_geometry = _requested_ffsf_fallback_geometry()
        shadow_enabled = (
            native_kernel is not None
            and _requested_ffsf_fallback_geometry_shadow()
        )
        compact_native_geometry = (
            requested_fallback_geometry != "python"
            and not shadow_enabled
            and _native_kernel_has_fallback_geometry(native_kernel)
        )

        if compact_native_geometry:
            (
                feature_index,
                part_bboxes,
                geom_index,
                ring_index,
                geometry_data,
            ) = _read_ffsf_feature_index_only(ffsf_path)
        else:
            (
                feature_index,
                part_bboxes,
                geom_index,
                ring_index,
                geometry_data,
            ) = _read_ffsf_full_geometry(ffsf_path)

        return cls(
            feature_index=feature_index,
            part_bboxes=part_bboxes,
            geom_index=geom_index,
            ring_index=ring_index,
            geometry_data=geometry_data,
            feature_meta_by_index=feature_meta_by_index,
            native_kernel=native_kernel,
        )

    def query_point(self, pt: Point, levels: list[int]) -> dict[int, dict]:
        """
        Return first matching feature per level, preserving feature index order.
        """
        if self.native_kernel is not None:
            native_hits = self.native_kernel.query_point_feature_indices(
                float(pt.x),
                float(pt.y),
                levels,
            )
            return self._feature_indices_to_hits(native_hits, source="polygon")

        level_set = set(levels)
        hits: dict[int, dict] = {}

        for feature_idx, feature in enumerate(self.feature_index):
            level = self._feature_level(feature_idx)
            if level not in level_set:
                continue
            if level in hits:
                continue

            if self._feature_contains_point(feature, pt):
                hits[level] = self._build_hit_from_feature_index(
                    feature_idx=feature_idx,
                    level=level,
                    source="polygon",
                )

            if len(hits) == len(level_set):
                break

        return hits

    def query_many_points(self, points: list[object], levels: list[int]) -> list[dict[int, dict]]:
        if self.native_kernel is not None:
            lons = [float(getattr(point, "x")) for point in points]
            lats = [float(getattr(point, "y")) for point in points]
            native_rows = self.native_kernel.query_many_feature_indices(lons, lats, levels)
            return [self._feature_indices_to_hits(row, source="polygon") for row in native_rows]
        return [self.query_point(point, levels) for point in points]  # type: ignore[arg-type]

    def _feature_indices_to_hits(self, native_hits: object, *, source: str) -> dict[int, dict]:
        if not isinstance(native_hits, dict):
            return {}
        hits: dict[int, dict] = {}
        feature_meta_count = len(self.feature_meta_by_index)
        for raw_level, raw_feature_idx in native_hits.items():
            if not isinstance(raw_level, int) or not isinstance(raw_feature_idx, int):
                continue
            if raw_feature_idx < 0 or raw_feature_idx >= feature_meta_count:
                continue
            hits[raw_level] = self._build_hit_from_feature_index(
                feature_idx=raw_feature_idx,
                level=raw_level,
                source=source,
            )
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
        if self._use_native_fallback_geometry():
            raw_hits = self._native_query_point_nearest_feature_indices(
                pt,
                max_distance_km=max_distance_km,
                levels=levels,
            )
        else:
            raw_hits = self._python_query_point_nearest_feature_indices(
                pt,
                max_distance_km=max_distance_km,
                levels=levels,
            )
        self._shadow_compare_nearest_feature_candidates(
            pt,
            max_distance_km=max_distance_km,
            levels=levels,
            production=raw_hits,
        )
        return self._feature_indices_to_hits(raw_hits, source="nearby")

    def has_country_scope_geometry(self) -> bool:
        return bool(self.country_scope_part_indices)

    def country_scope_contains_point(self, pt: Point) -> bool:
        if self._use_native_fallback_geometry():
            result = self._native_country_scope_contains_point(pt)
        else:
            result = self._python_country_scope_contains_point(pt)
        self._shadow_compare_country_scope_contains(pt, production=result)
        return result

    def _python_country_scope_contains_point(self, pt: Point) -> bool:
        for part_idx in self.country_scope_part_indices:
            if self._part_contains_point(part_idx, pt):
                return True
        return False

    def _native_country_scope_contains_point(self, pt: Point) -> bool:
        return bool(
            self.native_kernel.country_scope_contains_point(
                float(pt.x),
                float(pt.y),
                self.country_scope_part_indices,
            )
        )

    def distance_km_to_country_scope(self, pt: Point) -> float:
        if not self.country_scope_part_indices:
            return float("inf")
        if self._use_native_fallback_geometry():
            result = self._native_distance_km_to_country_scope(pt)
        else:
            result = self._python_distance_km_to_country_scope(pt)
        self._shadow_compare_distance(
            "country_scope_distance",
            pt,
            production=result,
            python_value_getter=lambda: self._python_distance_km_to_country_scope(pt),
            native_value_getter=lambda: self._native_distance_km_to_country_scope(pt),
        )
        return result

    def _python_distance_km_to_country_scope(self, pt: Point) -> float:
        if self._python_country_scope_contains_point(pt):
            return 0.0

        min_dist = float("inf")
        for part_idx in self.country_scope_part_indices:
            minx, miny, maxx, maxy = self.part_bboxes[part_idx]
            dist = self._distance_km_to_part(pt, part_idx, minx, miny, maxx, maxy)
            if dist < min_dist:
                min_dist = dist
        return min_dist

    def _native_distance_km_to_country_scope(self, pt: Point) -> float:
        return float(
            self.native_kernel.distance_km_to_country_scope(
                float(pt.x),
                float(pt.y),
                self.country_scope_part_indices,
            )
        )

    def distance_km_to_feature_id(self, pt: Point, feature_id: str) -> float:
        feature_idx = self.feature_id_to_index.get(feature_id)
        if feature_idx is None:
            return float("inf")
        if self._use_native_fallback_geometry():
            result = self._native_distance_km_to_feature_index(pt, feature_idx)
        else:
            result = self._python_distance_km_to_feature_index(pt, feature_idx)
        self._shadow_compare_distance(
            "feature_distance",
            pt,
            production=result,
            python_value_getter=lambda: self._python_distance_km_to_feature_index(pt, feature_idx),
            native_value_getter=lambda: self._native_distance_km_to_feature_index(pt, feature_idx),
            extra={"feature_id": feature_id, "feature_idx": feature_idx},
        )
        return result

    def _python_distance_km_to_feature_index(self, pt: Point, feature_idx: int) -> float:
        feature = self.feature_index[feature_idx]
        min_dist = float("inf")
        for part_idx in range(feature.part_start_idx, feature.part_start_idx + feature.part_count):
            minx, miny, maxx, maxy = self.part_bboxes[part_idx]
            dist = self._distance_km_to_part(pt, part_idx, minx, miny, maxx, maxy)
            if dist < min_dist:
                min_dist = dist
        return min_dist

    def _native_distance_km_to_feature_index(self, pt: Point, feature_idx: int) -> float:
        return float(
            self.native_kernel.distance_km_to_feature_index(
                float(pt.x),
                float(pt.y),
                feature_idx,
            )
        )

    def _python_query_point_nearest_feature_indices(
        self,
        pt: Point,
        *,
        max_distance_km: float,
        levels: list[int],
    ) -> dict[int, int]:
        level_set = set(levels)
        max_km = float(max_distance_km)
        threshold_deg = max_km / 111.0

        qminx = pt.x - threshold_deg
        qmaxx = pt.x + threshold_deg
        qminy = pt.y - threshold_deg
        qmaxy = pt.y + threshold_deg

        nearest_by_level: dict[int, tuple[float, int]] = {}

        for part_idx, (minx, miny, maxx, maxy) in enumerate(self.part_bboxes):
            if maxx < qminx or minx > qmaxx or maxy < qminy or miny > qmaxy:
                continue

            feature_idx = self.part_feature_index[part_idx]
            if feature_idx < 0:
                continue
            level = self._feature_level(feature_idx)
            if level not in level_set:
                continue

            dist_km = self._distance_km_to_part(pt, part_idx, minx, miny, maxx, maxy)
            if dist_km > max_km:
                continue

            best = nearest_by_level.get(level)
            if best is None or dist_km < best[0]:
                nearest_by_level[level] = (dist_km, feature_idx)

        return {level: feature_idx for level, (_, feature_idx) in nearest_by_level.items()}

    def _native_query_point_nearest_feature_indices(
        self,
        pt: Point,
        *,
        max_distance_km: float,
        levels: list[int],
    ) -> dict[int, int]:
        native_hits = self.native_kernel.query_point_nearest_feature_indices(
            float(pt.x),
            float(pt.y),
            float(max_distance_km),
            levels,
            self.part_feature_index,
        )
        if not isinstance(native_hits, dict):
            return {}
        hits: dict[int, int] = {}
        for raw_level, raw_feature_idx in native_hits.items():
            if isinstance(raw_level, int) and isinstance(raw_feature_idx, int):
                hits[raw_level] = raw_feature_idx
        return hits

    def _shadow_compare_country_scope_contains(
        self,
        pt: Point,
        *,
        production: bool,
    ) -> None:
        if not self._fallback_geometry_shadow_enabled:
            return
        self._run_shadow_compare(
            "country_scope_contains",
            pt,
            production=production,
            compare=lambda: self._compare_boolean_fact(
                python_value=self._python_country_scope_contains_point(pt),
                native_value=self._native_country_scope_contains_point(pt),
            ),
        )

    def _shadow_compare_distance(
        self,
        operation: str,
        pt: Point,
        *,
        production: float,
        python_value_getter,
        native_value_getter,
        extra: dict | None = None,
    ) -> None:
        if not self._fallback_geometry_shadow_enabled:
            return
        self._run_shadow_compare(
            operation,
            pt,
            production=production,
            extra=extra,
            compare=lambda: self._compare_distance_fact(
                python_value=float(python_value_getter()),
                native_value=float(native_value_getter()),
            ),
        )

    def _shadow_compare_nearest_feature_candidates(
        self,
        pt: Point,
        *,
        max_distance_km: float,
        levels: list[int],
        production: dict[int, int],
    ) -> None:
        if not self._fallback_geometry_shadow_enabled:
            return
        self._run_shadow_compare(
            "nearest_feature_candidates",
            pt,
            production=production,
            extra={
                "max_distance_km": float(max_distance_km),
                "levels": list(levels),
            },
            compare=lambda: self._compare_candidate_fact(
                python_value=self._python_query_point_nearest_feature_indices(
                    pt,
                    max_distance_km=max_distance_km,
                    levels=levels,
                ),
                native_value=self._native_query_point_nearest_feature_indices(
                    pt,
                    max_distance_km=max_distance_km,
                    levels=levels,
                ),
            ),
        )

    def _run_shadow_compare(
        self,
        operation: str,
        pt: Point,
        *,
        production: object,
        compare,
        extra: dict | None = None,
    ) -> None:
        try:
            severity, diff = compare()
        except Exception as exc:
            self._emit_fallback_geometry_shadow_diff(
                operation=operation,
                pt=pt,
                severity=3,
                production=production,
                diff={"error": repr(exc)},
                extra=extra,
            )
            return
        if severity == 0:
            return
        self._emit_fallback_geometry_shadow_diff(
            operation=operation,
            pt=pt,
            severity=severity,
            production=production,
            diff=diff,
            extra=extra,
        )

    def _compare_boolean_fact(
        self,
        *,
        python_value: bool,
        native_value: bool,
    ) -> tuple[int, dict]:
        if python_value == native_value:
            return 0, {}
        return 3, {
            "python": python_value,
            "native": native_value,
            "reason": "classification_mismatch",
        }

    def _compare_distance_fact(
        self,
        *,
        python_value: float,
        native_value: float,
    ) -> tuple[int, dict]:
        if python_value == native_value or (
            math.isinf(python_value) and math.isinf(native_value)
        ):
            return 0, {}
        delta = abs(python_value - native_value)
        tolerance = self._fallback_geometry_shadow_distance_tolerance_km
        if delta <= tolerance:
            severity = 1
            reason = "numeric_diff_within_tolerance"
        else:
            severity = 3
            reason = "distance_mismatch_outside_tolerance"
        return severity, {
            "python": python_value,
            "native": native_value,
            "delta_km": delta,
            "tolerance_km": tolerance,
            "reason": reason,
        }

    def _compare_candidate_fact(
        self,
        *,
        python_value: dict[int, int],
        native_value: dict[int, int],
    ) -> tuple[int, dict]:
        if python_value == native_value:
            return 0, {}
        python_levels = sorted(python_value)
        native_levels = sorted(native_value)
        if python_levels != native_levels:
            return 3, {
                "python": python_value,
                "native": native_value,
                "python_levels": python_levels,
                "native_levels": native_levels,
                "reason": "classification_mismatch",
            }
        return 2, {
            "python": python_value,
            "native": native_value,
            "levels": python_levels,
            "reason": "candidate_diff_same_classification",
        }

    def _emit_fallback_geometry_shadow_diff(
        self,
        *,
        operation: str,
        pt: Point,
        severity: int,
        production: object,
        diff: dict,
        extra: dict | None = None,
    ) -> None:
        payload = {
            "event": "ffsf_fallback_geometry_shadow_diff",
            "operation": operation,
            "severity": severity,
            "severity_label": {
                1: "numeric_diff_within_tolerance",
                2: "candidate_diff_same_classification",
                3: "classification_mismatch",
            }.get(severity, "identical"),
            "lon": float(pt.x),
            "lat": float(pt.y),
            "production_backend": self.fallback_geometry_backend_name,
            "production": production,
            "diff": diff,
        }
        if extra:
            payload.update(extra)
        log_method = _LOGGER.warning if severity >= 2 else _LOGGER.info
        log_method(
            "[FFSFNativeFallbackGeometryShadow] %s",
            json.dumps(payload, sort_keys=True),
        )

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

    def _has_native_fallback_geometry(self) -> bool:
        return _native_kernel_has_fallback_geometry(self.native_kernel)

    def _use_native_fallback_geometry(self) -> bool:
        if self._native_fallback_geometry == "python":
            return False
        has_native = self._has_native_fallback_geometry()
        if self._native_fallback_geometry == "native" and not has_native:
            raise RuntimeError(
                "CADIS_FFSF_FALLBACK_GEOMETRY=native requires native FFSF "
                "fallback geometry methods"
            )
        return has_native

    def _can_release_python_geometry(self) -> bool:
        if self._fallback_geometry_shadow_enabled:
            return False
        return self._native_fallback_geometry != "python" and self._has_native_fallback_geometry()

    def _release_python_geometry(self) -> None:
        self.feature_index = []
        self.part_bboxes = []
        self.geom_index = []
        self.ring_index = []
        self.geometry_data = memoryview(b"")
        self._python_geometry_retained = False

    def _require_python_geometry(self) -> None:
        if not self._python_geometry_retained:
            raise RuntimeError(
                "Python FFSF geometry is not retained because native fallback "
                "geometry is active"
            )

    def _feature_contains_point(self, feature: FeatureIndexEntry, pt: Point) -> bool:
        self._require_python_geometry()
        for part_idx in range(feature.part_start_idx, feature.part_start_idx + feature.part_count):
            if self._part_contains_point(part_idx, pt):
                return True
        return False

    def _part_contains_point(self, part_idx: int, pt: Point) -> bool:
        self._require_python_geometry()
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
        self._require_python_geometry()
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
        self._require_python_geometry()
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
