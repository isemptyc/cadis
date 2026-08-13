"""Open-sea download-candidate suggestion (NE inland-water / coastal-gap recovery).

The world classifier marks inland rivers as open sea, so a point genuinely inside a
country (e.g. on the Amazon River) resolves to open sea before that country's dataset
is installed. lookup() now surfaces supported, not-yet-installed countries whose
world-data bbox contains the point as `result.download_candidates`, and the CLI offers
to install one and re-resolve.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

# A point on the Amazon River, deep inside Brazil, that NE classifies as open sea.
AMAZON_LAT = -1.4602432024587475
AMAZON_LON = -52.14440934605092


def _reload_modules() -> None:
    for name in ["cadis", "cadis._api", "cadis._manager", "cadis._sdk"]:
        sys.modules.pop(name, None)


# --------------------------------------------------------------------------- #
# Real bundled CGD — the inland Amazon point falls inside Brazil's country bbox
# --------------------------------------------------------------------------- #

def test_cgd_country_bbox_candidates_includes_brazil() -> None:
    # Other test modules swap sys.modules["cadis.world"] for a bare fake; restore the
    # real package so this test is order-independent.
    for name in [n for n in list(sys.modules) if n == "cadis.world" or n.startswith("cadis.world.")]:
        sys.modules.pop(name, None)
    cgd_binary = importlib.import_module("cadis.world.cgd_binary")
    CGDReader = cgd_binary.CGDReader

    cgd_path = Path(cgd_binary.__file__).parent / "data" / "ne.global.v0.1.0.cgd"
    reader = CGDReader(cgd_path)

    candidates = reader.country_bbox_candidates(AMAZON_LON, AMAZON_LAT)
    assert "BR" in candidates
    # Open ocean far from any landmass yields no country bbox.
    assert reader.country_bbox_candidates(-150.0, 0.0) == []


def _real_world_resolver():
    for name in [n for n in list(sys.modules) if n == "cadis.world" or n.startswith("cadis.world.")]:
        sys.modules.pop(name, None)
    resolver_module = importlib.import_module("cadis.world.cgd_world_resolver")
    cgd_path = Path(resolver_module.__file__).parent / "data" / "ne.global.v0.1.0.cgd"
    return resolver_module.CGDWorldResolver(cgd_path=cgd_path)


def test_macao_photo_recognition_override_covers_cotai_and_airport() -> None:
    resolver = _real_world_resolver()

    for lat, lon in [(22.1450, 113.5650), (22.1496, 113.5915)]:
        out = resolver.resolve(lat, lon)
        assert out["lookup_status"] == "ok"
        assert out["resolution_method"] == "land_override"
        assert out["country"] == {"iso2": "MO", "name": "Macao"}
        assert out["land_override"]["id"] == "photolens-curator:mo_macao"
        assert resolver.country_bbox_candidates(lat, lon)[0] == "MO"


def test_macao_photo_recognition_override_excludes_adjacent_water() -> None:
    resolver = _real_world_resolver()

    out = resolver.resolve(22.15, 113.61)
    assert out["lookup_status"] == "ok"
    assert out["resolution_method"] == "open_sea"
    assert out["world_result"] == {"type": "open_sea", "name": "South China Sea"}


def test_hong_kong_photo_recognition_override_repairs_cgd_coastal_gaps() -> None:
    resolver = _real_world_resolver()

    for lat, lon in [
        (22.2819, 114.1589),  # Central
        (22.3015, 114.1567),  # West Kowloon
        (22.3129, 114.0413),  # Disneyland
        (22.3080, 113.9185),  # airport terminal
        (22.3060, 114.2580),  # Tseung Kwan O
    ]:
        out = resolver.resolve(lat, lon)
        assert out["lookup_status"] == "ok"
        assert out["resolution_method"] == "land_override"
        assert out["country"] == {"iso2": "HK", "name": "Hong Kong"}
        assert out["land_override"]["id"] == "photolens-curator:hk_hong_kong"


def test_hong_kong_override_does_not_replace_existing_china_classification() -> None:
    resolver = _real_world_resolver()

    out = resolver.resolve(22.5375, 114.1178)  # Luohu, Shenzhen side
    assert out["lookup_status"] == "ok"
    assert out.get("resolution_method") is None
    assert out["country"] == {"iso2": "CN", "name": "China"}


def test_hong_kong_override_excludes_outer_open_water() -> None:
    resolver = _real_world_resolver()

    out = resolver.resolve(22.10, 114.20)
    assert out["lookup_status"] == "ok"
    assert out["resolution_method"] == "open_sea"


def test_hong_kong_batch_override_matches_single_lookup_and_country_precedence() -> None:
    resolver = _real_world_resolver()
    lons = [114.1589, 114.1178]
    lats = [22.2819, 22.5375]

    batch = resolver.resolve_many_lons_lats(lons, lats)
    single = [resolver.resolve(lat, lon) for lon, lat in zip(lons, lats)]
    for item in batch + single:
        item.pop("resolved_at", None)
    assert batch == single
    assert batch[0]["country"]["iso2"] == "HK"
    assert batch[0]["resolution_method"] == "land_override"
    assert batch[1]["country"]["iso2"] == "CN"
    assert "resolution_method" not in batch[1]


def test_maldives_destination_envelope_recognizes_resort_and_lagoon_photos() -> None:
    resolver = _real_world_resolver()

    for lat, lon in [
        (4.2850, 73.4270),   # Baros lagoon
        (5.7260, 73.4150),   # Soneva Jani
        (3.6170, 72.7240),   # Conrad Rangali
        (-0.6930, 73.1550),  # Gan / Addu Atoll
    ]:
        out = resolver.resolve(lat, lon)
        assert out["lookup_status"] == "ok"
        assert out["resolution_method"] == "land_override"
        assert out["country"] == {"iso2": "MV", "name": "Maldives"}
        assert out["land_override"]["id"] == "photolens-curator:mv_maldives"
        assert resolver.country_bbox_candidates(lat, lon)[0] == "MV"


def test_maldives_override_preserves_existing_country_classification() -> None:
    resolver = _real_world_resolver()

    out = resolver.resolve(4.1755, 73.5093)  # Malé
    assert out["lookup_status"] == "ok"
    assert out.get("resolution_method") is None
    assert out["country"] == {"iso2": "MV", "name": "Maldives"}


def test_maldives_destination_envelope_excludes_outer_indian_ocean() -> None:
    resolver = _real_world_resolver()

    for lat, lon in [(4.0, 72.0), (4.0, 74.2)]:
        out = resolver.resolve(lat, lon)
        assert out["lookup_status"] == "ok"
        assert out["resolution_method"] == "open_sea"


def test_maldives_batch_override_matches_single_lookup_and_country_precedence() -> None:
    resolver = _real_world_resolver()
    lons = [73.4270, 73.5093]
    lats = [4.2850, 4.1755]

    batch = resolver.resolve_many_lons_lats(lons, lats)
    single = [resolver.resolve(lat, lon) for lon, lat in zip(lons, lats)]
    for item in batch + single:
        item.pop("resolved_at", None)
    assert batch == single
    assert batch[0]["country"]["iso2"] == "MV"
    assert batch[0]["resolution_method"] == "land_override"
    assert batch[1]["country"]["iso2"] == "MV"
    assert "resolution_method" not in batch[1]


# --------------------------------------------------------------------------- #
# _api candidate filtering — supported, not installed, allowlisted
# --------------------------------------------------------------------------- #

def _manager(candidates: list[str], *, allowed: bool = True) -> SimpleNamespace:
    class _GlobalLookup:
        def country_bbox_candidates(self, lat: float, lon: float) -> list[str]:
            return candidates

    return SimpleNamespace(
        get_or_init_global_lookup=lambda: _GlobalLookup(),
        is_iso2_allowed=lambda iso2: allowed,
    )


def test_candidates_keep_supported_drop_unsupported(tmp_path: Path) -> None:
    from cadis import _api

    manager = _manager(["BR", "QQ"])  # QQ is not a supported ISO2
    out = _api._open_sea_download_candidates(manager, lat=AMAZON_LAT, lon=AMAZON_LON, cache_dir=str(tmp_path))
    assert [c["iso2"] for c in out] == ["BR"]
    assert out[0]["name"]  # a human label is attached


def test_candidates_exclude_already_installed(tmp_path: Path) -> None:
    from cadis import _api

    (tmp_path / "BR").mkdir()  # BR dataset already present in the cache
    manager = _manager(["BR"])
    out = _api._open_sea_download_candidates(manager, lat=AMAZON_LAT, lon=AMAZON_LON, cache_dir=str(tmp_path))
    assert out == []


def test_candidates_respect_allowlist(tmp_path: Path) -> None:
    from cadis import _api

    manager = _manager(["BR"], allowed=False)
    out = _api._open_sea_download_candidates(manager, lat=AMAZON_LAT, lon=AMAZON_LON, cache_dir=str(tmp_path))
    assert out == []


# --------------------------------------------------------------------------- #
# lookup() integration — open-sea result carries download candidates
# --------------------------------------------------------------------------- #

def test_lookup_open_sea_surfaces_download_candidates(monkeypatch, tmp_path: Path) -> None:
    class _GlobalLookupImpl:
        @classmethod
        def from_defaults(cls):
            return cls()

        def lookup(self, lat: float, lon: float):
            return {
                "lookup_status": "ok",
                "world_context": {"world_result": {"type": "open_sea", "name": "Amazon River"}},
            }

        def country_bbox_candidates(self, lat: float, lon: float):
            return ["BR"]

    cadis_world = ModuleType("cadis.world")
    cadis_world.GlobalLookup = _GlobalLookupImpl
    sys.modules["cadis.world"] = cadis_world

    _reload_modules()
    cadis = importlib.import_module("cadis")

    monkeypatch.setenv("CADIS_CACHE_DIR", str(tmp_path))  # nothing installed → no offshore retry
    payload = cadis.lookup(AMAZON_LAT, AMAZON_LON)

    assert payload["execution"]["resolution_state"] == "open_sea"
    assert payload["state"]["world"]["classification"] == "open_sea"
    candidates = payload["result"]["download_candidates"]
    assert [c["iso2"] for c in candidates] == ["BR"]
