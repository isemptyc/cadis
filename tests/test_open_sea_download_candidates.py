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
