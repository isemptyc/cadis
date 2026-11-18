"""The water body dataset is bundled in the package (like the CGD), so named
water bodies resolve out of the box — no download, no prompt, no setup.
"""

from __future__ import annotations

import sys
from pathlib import Path

# A point on Lake Taupō, New Zealand (land point that also sits inside a lake).
TAUPO_LAT = -38.75122492478569
TAUPO_LON = 175.87743741652008


def _real_waterbody_module():
    # Defend against other test modules swapping cadis submodules in sys.modules.
    for name in [n for n in list(sys.modules) if n == "cadis.waterbody" or n.startswith("cadis.waterbody.")]:
        sys.modules.pop(name, None)
    import importlib

    return importlib.import_module("cadis.waterbody.waterbody_index")


def test_waterbody_dataset_is_bundled_in_package() -> None:
    wb = _real_waterbody_module()
    data_dir = wb.WaterbodyIndex.bundled_data_dir()
    assert data_dir is not None
    assert (data_dir / "waterbody.ffsf").is_file()
    assert (data_dir / "waterbody_meta.json").is_file()
    assert wb.BUNDLED_WATERBODY_VERSION == "v1.0.6"


def test_from_bundled_resolves_lake_taupo() -> None:
    wb = _real_waterbody_module()
    index = wb.WaterbodyIndex.from_bundled()
    assert index is not None

    record = index.lookup_record(TAUPO_LAT, TAUPO_LON)
    assert record is not None
    assert record["name"] == "Lake Taupo"
    assert record["names"].get("native") == "Taupō"
    assert record["feature_id"]


def test_manager_uses_bundled_waterbody_without_cache(tmp_path: Path) -> None:
    """With nothing installed in the cache, the manager still serves the bundled index."""
    for name in [n for n in list(sys.modules) if n == "cadis._manager" or n.startswith("cadis._manager.")]:
        sys.modules.pop(name, None)
    import importlib

    CadisManager = importlib.import_module("cadis._manager").CadisManager

    manager = CadisManager(default_cache_dir=tmp_path)  # empty cache dir
    index = manager.get_waterbody_index()
    assert index is not None
    assert index.lookup(TAUPO_LAT, TAUPO_LON) == "Lake Taupo"


def test_manager_ignores_cache_copy_dataset_is_pinned(tmp_path: Path) -> None:
    """The bundled dataset is pinned: a copy installed in the cache is NOT consulted."""
    from tests.test_waterbody_lookup import _write_waterbody_dataset

    for name in [n for n in list(sys.modules) if n == "cadis._manager" or n.startswith("cadis._manager.")]:
        sys.modules.pop(name, None)
    import importlib

    CadisManager = importlib.import_module("cadis._manager").CadisManager

    # Install a different water body in the cache that would (wrongly) cover Taupō.
    _write_waterbody_dataset(
        tmp_path / "_global" / "waterbody.global" / "v9.9.9",
        {
            "feature_id": "cache_only",
            "name": "Cache Lake",
            "names": {"en": "Cache Lake"},
            "bbox": [175.0, -39.0, 176.0, -38.0],
        },
    )

    manager = CadisManager(default_cache_dir=tmp_path)
    # Pinned bundled dataset wins; the cache copy ("Cache Lake") is never used.
    assert manager.get_waterbody_index().lookup(TAUPO_LAT, TAUPO_LON) == "Lake Taupo"


def test_tagus_estuary_and_nearby_lisbon_land() -> None:
    index = _real_waterbody_module().WaterbodyIndex.from_bundled()
    assert index is not None

    estuary = index.lookup_record(38.766572, -9.075)
    assert estuary is not None
    assert estuary["name"] == "Tagus River"
    assert estuary["names"]["zh-Hant-TW"] == "太加斯河"
    assert index.lookup(39.23792115, -8.663492957433157) == "Tagus River"
    assert index.lookup(38.7665722222222, -9.09865555555556) is None
    assert index.lookup(38.7, -9.5) == "Atlantic Ocean"


def test_lisbon_land_override_leaves_tagus_estuary_as_water() -> None:
    from cadis.world.cgd_world_resolver import CGDWorldResolver

    cgd_path = Path(__file__).resolve().parents[1] / "cadis/world/data/ne.global.v0.1.0.cgd"
    resolver = CGDWorldResolver(cgd_path=cgd_path)

    photo = resolver.resolve(38.7665722222222, -9.09865555555556)
    assert photo["country"]["iso2"] == "PT"
    assert photo["resolution_method"] == "land_override"

    estuary = resolver.resolve(38.766572, -9.075)
    assert estuary["world_result"]["type"] == "open_sea"


def test_belem_shoreline_can_match_portugal_and_tagus() -> None:
    from cadis.world.cgd_world_resolver import CGDWorldResolver

    cgd_path = Path(__file__).resolve().parents[1] / "cadis/world/data/ne.global.v0.1.0.cgd"
    resolver = CGDWorldResolver(cgd_path=cgd_path)
    index = _real_waterbody_module().WaterbodyIndex.from_bundled()
    assert index is not None

    photo = (38.6933694444444, -9.20629444444444)
    assert resolver.resolve(*photo)["country"]["iso2"] == "PT"
    waterbody = index.lookup_record(*photo)
    assert waterbody is not None
    assert waterbody["names"]["zh-Hant-TW"] == "太加斯河"

    # The river side stays open water, while the inland side leaves Tagus coverage.
    river = (38.6932694444444, photo[1])
    inland = (38.6934694444444, photo[1])
    assert resolver.resolve(*river)["world_result"]["type"] == "open_sea"
    assert index.lookup(*river) == "Tagus River"
    assert resolver.resolve(*inland)["country"]["iso2"] == "PT"
    assert index.lookup(*inland) != "Tagus River"


def test_mainland_spain_coastal_gaps_leave_open_water_and_gibraltar() -> None:
    from cadis.world.cgd_world_resolver import CGDWorldResolver

    cgd_path = Path(__file__).resolve().parents[1] / "cadis/world/data/ne.global.v0.1.0.cgd"
    resolver = CGDWorldResolver(cgd_path=cgd_path)

    for land in ((39.4725, -0.3236), (36.7174, -4.41), (43.4613, -3.8047)):
        result = resolver.resolve(*land)
        assert result["country"]["iso2"] == "ES"
        assert result["resolution_method"] == "land_override"

    assert resolver.resolve(39.4725, -0.30)["world_result"]["type"] == "open_sea"
    assert resolver.resolve(36.12677731661892, -5.3456406617257555)["country"]["iso2"] == "GI"
