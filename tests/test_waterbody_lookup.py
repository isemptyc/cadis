"""Waterbody-on-land parity tests (ported from Swift CadisKit).

A coordinate may fall inside both an administrative polygon and a named water
body. The Swift engine surfaces both; these tests pin the same behaviour for the
Python ``lookup`` + CLI surfaces. Coordinates and expectations come from the
shared, engine-neutral fixture ``fixtures/waterbody_parity_points.json`` so the
same point-set can be cross-checked against Swift ``cadis-lookup``.
"""

from __future__ import annotations

import importlib
import json
import struct
import sys
from pathlib import Path
from types import ModuleType

import pytest

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "waterbody_parity_points.json").read_text(encoding="utf-8")
)


def _reload_modules() -> None:
    for name in ["cadis", "cadis._api", "cadis._manager", "cadis._sdk"]:
        sys.modules.pop(name, None)


def _write_waterbody_dataset(version_dir: Path, polygon: dict) -> None:
    """Write a one-feature/one-part FFSF v3 water body whose polygon fills ``bbox``."""
    version_dir.mkdir(parents=True)
    minx, miny, maxx, maxy = polygon["bbox"]
    # Outer ring = the bbox square, in quantized uint16 [0, 65535] space.
    ring = [(0, 0), (65535, 0), (65535, 65535), (0, 65535), (0, 0)]
    geom = b"".join(struct.pack("<HH", x, y) for x, y in ring)

    blob = bytearray()
    blob += b"FFSF"
    blob += struct.pack("<III", 3, 1, 1)              # version, feature_count, part_count
    blob += struct.pack("<4I", 0, 0, 0, 1)            # feature: _, _, part_start, part_count
    blob += struct.pack("<4f", minx, miny, maxx, maxy)  # part bbox
    blob += struct.pack("<4I", 0, len(geom), 0, 1)    # geom: byte_offset, byte_len, ring_start, ring_count
    blob += struct.pack("<I", len(ring))              # ring point count
    blob += geom
    (version_dir / "waterbody.ffsf").write_bytes(bytes(blob))
    (version_dir / "waterbody_meta.json").write_text(
        json.dumps([
            {
                "feature_id": polygon["feature_id"],
                "name": polygon["name"],
                "names": polygon["names"],
            }
        ]),
        encoding="utf-8",
    )


def _patch_bundled_waterbody(monkeypatch, tmp_path: Path) -> None:
    """Make the pinned/bundled water body loader serve the synthetic fixture polygon.

    The water body index is served only from the package-bundled dataset (no cache
    fallback), so tests inject their controlled polygon by patching `from_bundled`.
    """
    from cadis.waterbody.waterbody_index import WaterbodyIndex

    version_dir = tmp_path / "_bundled_waterbody"
    _write_waterbody_dataset(version_dir, FIXTURE["waterbody_polygon"])
    index = WaterbodyIndex(version_dir)
    monkeypatch.setattr(WaterbodyIndex, "from_bundled", staticmethod(lambda: index))


# --------------------------------------------------------------------------- #
# Direct index test — real point-in-polygon + structured shape
# --------------------------------------------------------------------------- #

def test_waterbody_index_returns_structured_record(tmp_path: Path) -> None:
    from cadis.waterbody import WaterbodyIndex

    version_dir = tmp_path / "_global" / "waterbody.global" / "v1.0.3"
    _write_waterbody_dataset(version_dir, FIXTURE["waterbody_polygon"])
    index = WaterbodyIndex(version_dir)

    poly = FIXTURE["waterbody_polygon"]
    inside = next(p for p in FIXTURE["points"] if p["id"] == "land-inside-bay")
    outside = next(p for p in FIXTURE["points"] if p["id"] == "land-outside-bay")

    record = index.lookup_record(inside["lat"], inside["lon"])
    assert record == {
        "name": poly["name"],
        "feature_id": poly["feature_id"],
        "names": poly["names"],
    }
    # Name-only helper stays in sync with the structured record.
    assert index.lookup(inside["lat"], inside["lon"]) == poly["name"]

    # A point outside the polygon bbox is a clean miss.
    assert index.lookup_record(outside["lat"], outside["lon"]) is None


# --------------------------------------------------------------------------- #
# lookup() — land coordinate inside both an admin polygon and a water body
# --------------------------------------------------------------------------- #

def _install_country_world_fakes() -> None:
    country = FIXTURE["country"]
    admin_hierarchy = country["admin_hierarchy"]

    class _GlobalLookupImpl:
        @classmethod
        def from_defaults(cls):
            return cls()

        def lookup(self, lat: float, lon: float):
            return {
                "lookup_status": "ok",
                "world_context": {"country": {"iso2": country["iso2"], "name": country["name"]}},
            }

    class _Runtime:
        def __init__(self, *, dataset_dir: str):
            self.dataset_dir = dataset_dir

        def lookup(self, lat: float, lon: float):
            return {
                "lookup_status": "ok",
                "result": {
                    "country": {"name": country["name"]},
                    "admin_hierarchy": [dict(node) for node in admin_hierarchy],
                    "source": "polygon",
                },
            }

    cadis_world = ModuleType("cadis.world")
    cadis_world.GlobalLookup = _GlobalLookupImpl
    sys.modules["cadis.world"] = cadis_world

    cadis_runtime = ModuleType("cadis.runtime")
    cadis_runtime.inspect_dataset = lambda dataset_dir: {"state": {"dataset": {"status": "ready"}}}
    cadis_runtime.CadisRuntime = _Runtime
    sys.modules["cadis.runtime"] = cadis_runtime

    cadis_cdn = ModuleType("cadis.cdn")
    cadis_cdn.parse_version_for_sort = lambda raw: (1, 0, 1)
    sys.modules["cadis.cdn"] = cadis_cdn


def test_lookup_land_point_attaches_waterbody(monkeypatch, tmp_path: Path) -> None:
    """Land coordinate inside a water body → admin hierarchy AND waterbody."""
    from tests.test_control_layer import _write_minimal_offshore_dataset

    _install_country_world_fakes()
    _reload_modules()
    cadis = importlib.import_module("cadis")

    cache_root = tmp_path
    _write_minimal_offshore_dataset(
        cache_root / FIXTURE["country"]["iso2"] / "it.admin" / "v1.0.1",
        bbox=tuple(FIXTURE["country"]["scope_bbox"]),
    )
    _patch_bundled_waterbody(monkeypatch, tmp_path)
    monkeypatch.setenv("CADIS_CACHE_DIR", str(cache_root))

    point = next(p for p in FIXTURE["points"] if p["id"] == "land-inside-bay")
    payload = cadis.lookup(point["lat"], point["lon"])

    assert payload["execution"]["lookup_status"] == "ok"
    assert payload["state"]["world"]["iso2"] == point["expect"]["iso2"]
    result = payload["result"]
    # Both surfaces present simultaneously.
    assert result["admin_hierarchy"][-1]["name"] == point["expect"]["admin_last"]
    assert result["waterbody"] == {
        "name": FIXTURE["waterbody_polygon"]["name"],
        "feature_id": FIXTURE["waterbody_polygon"]["feature_id"],
        "names": FIXTURE["waterbody_polygon"]["names"],
    }


def test_lookup_land_point_outside_waterbody_has_no_waterbody(monkeypatch, tmp_path: Path) -> None:
    from tests.test_control_layer import _write_minimal_offshore_dataset

    _install_country_world_fakes()
    _reload_modules()
    cadis = importlib.import_module("cadis")

    cache_root = tmp_path
    _write_minimal_offshore_dataset(
        cache_root / FIXTURE["country"]["iso2"] / "it.admin" / "v1.0.1",
        bbox=tuple(FIXTURE["country"]["scope_bbox"]),
    )
    _patch_bundled_waterbody(monkeypatch, tmp_path)
    monkeypatch.setenv("CADIS_CACHE_DIR", str(cache_root))

    point = next(p for p in FIXTURE["points"] if p["id"] == "land-outside-bay")
    payload = cadis.lookup(point["lat"], point["lon"])

    assert payload["execution"]["lookup_status"] == "ok"
    assert payload["result"]["admin_hierarchy"][-1]["name"] == point["expect"]["admin_last"]
    assert "waterbody" not in payload["result"]


# --------------------------------------------------------------------------- #
# lookup() — open-sea coordinate inside a water body, no offshore country
# --------------------------------------------------------------------------- #

def test_lookup_open_sea_point_attaches_waterbody(monkeypatch, tmp_path: Path) -> None:
    """Open-sea coordinate with no offshore candidate → open-sea output + waterbody."""
    class _GlobalLookupImpl:
        @classmethod
        def from_defaults(cls):
            return cls()

        def lookup(self, lat: float, lon: float):
            return {
                "lookup_status": "ok",
                "world_context": {"world_result": {"type": "open_sea", "name": "Adriatic Sea"}},
            }

    cadis_world = ModuleType("cadis.world")
    cadis_world.GlobalLookup = _GlobalLookupImpl
    sys.modules["cadis.world"] = cadis_world

    _reload_modules()
    cadis = importlib.import_module("cadis")

    cache_root = tmp_path
    # No country dataset installed → offshore retry finds no candidate.
    _patch_bundled_waterbody(monkeypatch, tmp_path)
    monkeypatch.setenv("CADIS_CACHE_DIR", str(cache_root))

    point = next(p for p in FIXTURE["points"] if p["id"] == "open-sea-inside-bay")
    payload = cadis.lookup(point["lat"], point["lon"])

    assert payload["execution"]["resolution_state"] == "open_sea"
    assert payload["state"]["world"]["classification"] == "open_sea"
    assert payload["result"]["waterbody"] == {
        "name": FIXTURE["waterbody_polygon"]["name"],
        "feature_id": FIXTURE["waterbody_polygon"]["feature_id"],
        "names": FIXTURE["waterbody_polygon"]["names"],
    }
    assert "admin_hierarchy" not in payload["result"]
