from __future__ import annotations

import math

import pytest

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


def test_native_fallback_geometry_routes_geometry_facts(monkeypatch):
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "native")
    index = _index(_NativeFallbackKernel())
    pt = Point(10.0, 20.0)

    assert index.fallback_geometry_backend_name == "native"
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


def test_native_fallback_geometry_requires_complete_native_contract(monkeypatch):
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "native")
    index = _index(object())

    with pytest.raises(RuntimeError, match="requires native FFSF fallback geometry"):
        index.country_scope_contains_point(Point(10.0, 20.0))


def test_native_fallback_geometry_requires_native_runtime(monkeypatch):
    monkeypatch.setenv("CADIS_FFSF_FALLBACK_GEOMETRY", "native")

    with pytest.raises(RuntimeError, match="requires a native FFSF runtime"):
        _index(None)
