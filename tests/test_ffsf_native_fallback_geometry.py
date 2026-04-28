from __future__ import annotations

import json
import math
import struct

import pytest

import cadis.runtime.dataset.ffsf_runtime as ffsf_mod
from cadis.runtime.dataset.ffsf_runtime import (
    FFSFSpatialIndexV3,
    FeatureIndexEntry,
    GeomIndexV2Entry,
    Point,
)


class _NativeFallbackKernel:
    backend_name = "native"

    def country_scope_contains_point(self, lon, lat, part_indices):
        return (lon, lat, part_indices) == (10.0, 20.0, [0])

    def query_point_feature_indices(self, lon, lat, levels):
        return {4: 0} if (lon, lat, levels) == (10.0, 20.0, [4]) else {}

    def distance_km_to_country_scope(self, lon, lat, part_indices):
        return 12.5

    def distance_km_to_feature_index(self, lon, lat, feature_idx):
        return 7.25

    def query_point_nearest_feature_indices(
        self,
        lon,
        lat,
        max_distance_km,
        levels,
        part_feature_indices,
    ):
        assert (lon, lat, max_distance_km) == (10.0, 20.0, 50.0)
        assert levels == [4]
        assert part_feature_indices == [0]
        return {4: 0}


class _ShadowNativeKernel:
    backend_name = "native"

    def __init__(
        self,
        *,
        contains=False,
        country_distance_km=0.0,
        feature_distance_km=0.0,
        nearest=None,
    ):
        self._contains = contains
        self._country_distance_km = country_distance_km
        self._feature_distance_km = feature_distance_km
        self._nearest = nearest if nearest is not None else {}

    def country_scope_contains_point(self, lon, lat, part_indices):
        return self._contains

    def distance_km_to_country_scope(self, lon, lat, part_indices):
        return self._country_distance_km

    def distance_km_to_feature_index(self, lon, lat, feature_idx):
        return self._feature_distance_km

    def query_point_nearest_feature_indices(
        self,
        lon,
        lat,
        max_distance_km,
        levels,
        part_feature_indices,
    ):
        return self._nearest


def _index(native_kernel) -> FFSFSpatialIndexV3:
    return FFSFSpatialIndexV3(
        feature_index=[FeatureIndexEntry(part_start_idx=0, part_count=1)],
        part_bboxes=[(0.0, 0.0, 1.0, 1.0)],
        geom_index=[
            GeomIndexV2Entry(
                byte_offset=0,
                byte_len=0,
                ring_start_idx=0,
                ring_count=0,
            )
        ],
        ring_index=[],
        geometry_data=memoryview(b""),
        feature_meta_by_index=[
            {
                "feature_id": "feature-1",
                "level": 4,
                "name": "Feature 1",
                "country_scope_flag": True,
            }
        ],
        native_kernel=native_kernel,
    )


def _square_index(native_kernel, *, feature_count=1) -> FFSFSpatialIndexV3:
    ring = [(0, 0), (65535, 0), (65535, 65535), (0, 65535), (0, 0)]
    geometry_data = struct.pack("<" + "H" * 10, *(coord for point in ring for coord in point))
    feature_index = []
    part_bboxes = []
    geom_index = []
    ring_index = []
    feature_meta_by_index = []
    offset = 0
    for feature_idx in range(feature_count):
        feature_index.append(FeatureIndexEntry(part_start_idx=feature_idx, part_count=1))
        shift = float(feature_idx * 10)
        part_bboxes.append((shift, 0.0, shift + 1.0, 1.0))
        geom_index.append(
            GeomIndexV2Entry(
                byte_offset=offset,
                byte_len=len(geometry_data),
                ring_start_idx=feature_idx,
                ring_count=1,
            )
        )
        ring_index.append(len(ring))
        feature_meta_by_index.append(
            {
                "feature_id": f"feature-{feature_idx}",
                "level": 4,
                "name": f"Feature {feature_idx}",
                "country_scope_flag": feature_idx == 0,
            }
        )
        offset += len(geometry_data)
    return FFSFSpatialIndexV3(
        feature_index=feature_index,
        part_bboxes=part_bboxes,
        geom_index=geom_index,
        ring_index=ring_index,
        geometry_data=memoryview(geometry_data * feature_count),
        feature_meta_by_index=feature_meta_by_index,
        native_kernel=native_kernel,
    )


def _shadow_payloads(caplog):
    payloads = []
    for record in caplog.records:
        marker = "[FFSFNativeFallbackGeometryShadow] "
        message = record.getMessage()
        if marker in message:
            payloads.append(json.loads(message.split(marker, 1)[1]))
    return payloads


def _write_minimal_ffsf_dataset(tmp_path):
    ffsf_path = tmp_path / "geometry.ffsf"
    meta_path = tmp_path / "geometry_meta.json"
    ffsf_path.write_bytes(
        b"FFSF"
        + struct.pack("<III", 3, 1, 1)
        + struct.pack("<4I", 0, 0, 0, 1)
        + struct.pack("<4f", 0.0, 0.0, 1.0, 1.0)
        + struct.pack("<4I", 0, 0, 0, 0)
    )
    meta_path.write_text(
        json.dumps(
            [
                {
                    "feature_id": "feature-1",
                    "level": 4,
                    "name": "Feature 1",
                    "country_scope_flag": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    return ffsf_path, meta_path


def test_native_fallback_geometry_routes_geometry_facts(monkeypatch):
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "native")
    index = _index(_NativeFallbackKernel())
    pt = Point(10.0, 20.0)

    assert index.fallback_geometry_backend_name == "native"
    assert index.python_geometry_retained is False
    assert index.country_scope_contains_point(pt) is True
    assert index.distance_km_to_country_scope(pt) == 12.5
    assert index.distance_km_to_feature_id(pt, "feature-1") == 7.25
    assert math.isinf(index.distance_km_to_feature_id(pt, "missing"))
    assert index.query_point_nearest(pt, max_distance_km=50.0, levels=[4]) == {
        4: {
            "level": 4,
            "name": "Feature 1",
            "osm_id": "feature-1",
            "source": "nearby",
        }
    }


def test_fallback_geometry_defaults_to_auto_with_native_contract(monkeypatch):
    monkeypatch.delenv("CADIS_FFSF_FALLBACK_GEOMETRY", raising=False)
    index = _index(_NativeFallbackKernel())

    assert index.fallback_geometry_backend_name == "native"
    assert index.python_geometry_retained is False
    assert index.feature_index == []
    assert index.part_bboxes == []
    assert index.geom_index == []
    assert index.ring_index == []
    assert bytes(index.geometry_data) == b""
    assert index.country_scope_contains_point(Point(10.0, 20.0)) is True


def test_fallback_geometry_defaults_to_python_without_native_runtime(monkeypatch):
    monkeypatch.delenv("CADIS_FFSF_FALLBACK_GEOMETRY", raising=False)
    index = _index(None)

    assert index.fallback_geometry_backend_name == "python"
    assert index.python_geometry_retained is True
    assert index.country_scope_contains_point(Point(10.0, 20.0)) is False


def test_from_files_skips_python_geometry_parse_in_native_compact_mode(monkeypatch, tmp_path):
    ffsf_path, meta_path = _write_minimal_ffsf_dataset(tmp_path)
    monkeypatch.delenv("CADIS_FFSF_FALLBACK_GEOMETRY", raising=False)
    monkeypatch.delenv("CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW", raising=False)
    monkeypatch.delenv("CADIS_TRIM_FEATURE_META", raising=False)
    monkeypatch.setattr(
        ffsf_mod,
        "_create_native_ffsf_kernel",
        lambda **_: _NativeFallbackKernel(),
    )

    index = FFSFSpatialIndexV3.from_files(
        ffsf_path=ffsf_path,
        feature_meta_path=meta_path,
    )

    assert index.fallback_geometry_backend_name == "native"
    assert index.python_geometry_retained is False
    assert index.part_feature_index == [0]
    assert index.country_scope_part_indices == [0]
    assert index.feature_index == []
    assert index.part_bboxes == []
    assert index.geom_index == []
    assert index.ring_index == []
    assert bytes(index.geometry_data) == b""


def test_from_files_trims_feature_meta_by_default(monkeypatch, tmp_path):
    ffsf_path, meta_path = _write_minimal_ffsf_dataset(tmp_path)
    meta_path.write_text(
        json.dumps(
            [
                {
                    "feature_id": "feature-1",
                    "level": 4,
                    "name": "Feature 1",
                    "names": {"en": "Feature 1", "zh": "Feature One"},
                    "country_scope_flag": True,
                    "unused_bbox": [0.0, 0.0, 1.0, 1.0],
                    "unused_rank": 123,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CADIS_FFSF_BACKEND", "python")
    monkeypatch.delenv("CADIS_TRIM_FEATURE_META", raising=False)

    index = FFSFSpatialIndexV3.from_files(
        ffsf_path=ffsf_path,
        feature_meta_path=meta_path,
    )

    assert index.feature_meta_by_index == [
        {
            "feature_id": "feature-1",
            "level": 4,
            "name": "Feature 1",
            "names": {"en": "Feature 1", "zh": "Feature One"},
            "country_scope_flag": True,
        }
    ]
    report = index.memory_report()
    assert report["feature_meta_total_key_count"] == 5
    assert report["feature_meta_unique_feature_id_count"] == 1
    assert report["feature_meta_unique_name_count"] == 1
    assert report["feature_meta_unique_localized_name_count"] == 2
    assert report["feature_meta_json_bytes"] < len(meta_path.read_bytes())


def test_feature_meta_trim_can_be_disabled(monkeypatch, tmp_path):
    ffsf_path, meta_path = _write_minimal_ffsf_dataset(tmp_path)
    meta_path.write_text(
        json.dumps(
            [
                {
                    "feature_id": "feature-1",
                    "level": 4,
                    "name": "Feature 1",
                    "country_scope_flag": True,
                    "unused_rank": 123,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CADIS_FFSF_BACKEND", "python")
    monkeypatch.setenv("CADIS_TRIM_FEATURE_META", "off")

    index = FFSFSpatialIndexV3.from_files(
        ffsf_path=ffsf_path,
        feature_meta_path=meta_path,
    )

    assert index.feature_meta_by_index[0]["unused_rank"] == 123
    assert index.memory_report()["feature_meta_total_key_count"] == 5


def test_columnar_feature_meta_mode_preserves_lookup_semantics(monkeypatch):
    monkeypatch.setenv("CADIS_FEATURE_META_MODE", "columnar")
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "python")
    dict_index = _square_index(None)
    monkeypatch.setenv("CADIS_FEATURE_META_MODE", "dict")
    expected_index = _square_index(None)

    pt = Point(0.5, 0.5)

    assert dict_index.query_point(pt, [4]) == expected_index.query_point(pt, [4])
    assert dict_index.query_point_nearest(
        Point(3.0, 0.5),
        max_distance_km=500.0,
        levels=[4],
    ) == expected_index.query_point_nearest(
        Point(3.0, 0.5),
        max_distance_km=500.0,
        levels=[4],
    )
    assert dict_index.distance_km_to_feature_id(pt, "feature-0") == (
        expected_index.distance_km_to_feature_id(pt, "feature-0")
    )
    assert dict_index.build_country_scope_allowlist(levels=[4]) == (
        expected_index.build_country_scope_allowlist(levels=[4])
    )
    assert isinstance(dict_index.feature_meta_by_index, ffsf_mod.FeatureMetaColumns)
    assert dict_index.memory_report()["feature_meta_mode"] == "columnar"
    assert dict_index.memory_report()["feature_meta_object_count"] == 0


def test_columnar_feature_meta_mode_preserves_native_hit_mapping(monkeypatch):
    monkeypatch.setenv("CADIS_FEATURE_META_MODE", "columnar")
    monkeypatch.delenv("CADIS_FFSF_FALLBACK_GEOMETRY", raising=False)
    index = _index(_NativeFallbackKernel())

    assert index.query_point(Point(10.0, 20.0), [4]) == {
        4: {
            "level": 4,
            "name": "Feature 1",
            "osm_id": "feature-1",
            "source": "polygon",
        }
    }
    assert isinstance(index.feature_meta_by_index, ffsf_mod.FeatureMetaColumns)


def test_columnar_hot_paths_bypass_feature_meta_view(monkeypatch):
    monkeypatch.setenv("CADIS_FEATURE_META_MODE", "columnar")
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "python")
    python_index = _square_index(None)
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "native")
    native_index = _index(_NativeFallbackKernel())

    def fail_get(self, key, default=None):
        raise AssertionError("hot path should not call FeatureMetaView.get")

    monkeypatch.setattr(ffsf_mod.FeatureMetaView, "get", fail_get)

    assert python_index.query_point(Point(0.5, 0.5), [4]) == {
        4: {
            "level": 4,
            "name": "Feature 0",
            "osm_id": "feature-0",
            "source": "polygon",
        }
    }
    assert python_index.query_point_nearest(
        Point(3.0, 0.5),
        max_distance_km=500.0,
        levels=[4],
    ) == {
        4: {
            "level": 4,
            "name": "Feature 0",
            "osm_id": "feature-0",
            "source": "nearby",
        }
    }
    assert native_index.query_point(Point(10.0, 20.0), [4]) == {
        4: {
            "level": 4,
            "name": "Feature 1",
            "osm_id": "feature-1",
            "source": "polygon",
        }
    }


def test_memory_report_exposes_released_geometry_counts(monkeypatch):
    monkeypatch.delenv("CADIS_FFSF_FALLBACK_GEOMETRY", raising=False)
    index = _index(_NativeFallbackKernel())

    report = index.memory_report()

    assert report["backend_name"] == "native"
    assert report["fallback_geometry_backend_name"] == "native"
    assert report["python_geometry_retained"] is False
    assert report["feature_count"] == 1
    assert report["part_count"] == 1
    assert report["feature_index_count"] == 0
    assert report["part_bbox_count"] == 0
    assert report["geom_index_count"] == 0
    assert report["ring_index_count"] == 0
    assert report["geometry_data_bytes"] == 0


def test_from_files_retains_python_geometry_for_shadow(monkeypatch, tmp_path):
    ffsf_path, meta_path = _write_minimal_ffsf_dataset(tmp_path)
    monkeypatch.delenv("CADIS_FFSF_FALLBACK_GEOMETRY", raising=False)
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW", "1")
    monkeypatch.setattr(
        ffsf_mod,
        "_create_native_ffsf_kernel",
        lambda **_: _NativeFallbackKernel(),
    )

    index = FFSFSpatialIndexV3.from_files(
        ffsf_path=ffsf_path,
        feature_meta_path=meta_path,
    )

    assert index.fallback_geometry_backend_name == "native"
    assert index.python_geometry_retained is True
    assert len(index.feature_index) == 1
    assert len(index.part_bboxes) == 1
    assert len(index.geom_index) == 1


def test_fallback_geometry_python_mode_retains_python_geometry(monkeypatch):
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "python")
    index = _index(_NativeFallbackKernel())

    assert index.fallback_geometry_backend_name == "python"
    assert index.python_geometry_retained is True
    assert len(index.feature_index) == 1
    assert len(index.part_bboxes) == 1


def test_native_fallback_geometry_requires_complete_native_contract(monkeypatch):
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "native")
    index = _index(object())

    with pytest.raises(RuntimeError, match="requires native FFSF fallback geometry"):
        index.country_scope_contains_point(Point(10.0, 20.0))


def test_native_fallback_geometry_requires_native_runtime(monkeypatch):
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "native")

    with pytest.raises(RuntimeError, match="requires a native FFSF runtime"):
        _index(None)


def test_fallback_geometry_shadow_logs_classification_mismatch_without_affecting_output(
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "python")
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW", "1")
    index = _index(_ShadowNativeKernel(contains=True))

    assert index.python_geometry_retained is True
    with caplog.at_level("INFO", logger="cadis.runtime.dataset.ffsf_runtime"):
        assert index.country_scope_contains_point(Point(10.0, 20.0)) is False

    payloads = _shadow_payloads(caplog)
    assert payloads[0]["operation"] == "country_scope_contains"
    assert payloads[0]["severity"] == 3
    assert payloads[0]["diff"]["reason"] == "classification_mismatch"
    assert payloads[0]["production_backend"] == "python"


def test_fallback_geometry_shadow_logs_distance_diff_within_tolerance(
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "python")
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW", "1")
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW_DISTANCE_TOLERANCE_KM", "0.001")
    index = _square_index(_ShadowNativeKernel(contains=True, country_distance_km=0.0005))

    with caplog.at_level("INFO", logger="cadis.runtime.dataset.ffsf_runtime"):
        assert index.distance_km_to_country_scope(Point(0.5, 0.5)) == 0.0

    payloads = _shadow_payloads(caplog)
    assert payloads[0]["operation"] == "country_scope_distance"
    assert payloads[0]["severity"] == 1
    assert payloads[0]["diff"]["reason"] == "numeric_diff_within_tolerance"


def test_fallback_geometry_shadow_logs_candidate_diff_same_classification(
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "python")
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW", "1")
    index = _square_index(_ShadowNativeKernel(nearest={4: 1}), feature_count=2)

    with caplog.at_level("INFO", logger="cadis.runtime.dataset.ffsf_runtime"):
        assert index.query_point_nearest(Point(0.5, 0.5), max_distance_km=2000.0, levels=[4]) == {
            4: {
                "level": 4,
                "name": "Feature 0",
                "osm_id": "feature-0",
                "source": "nearby",
            }
        }

    payloads = _shadow_payloads(caplog)
    assert payloads[0]["operation"] == "nearest_feature_candidates"
    assert payloads[0]["severity"] == 2
    assert payloads[0]["diff"]["reason"] == "candidate_diff_same_classification"
