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
    assert wb.BUNDLED_WATERBODY_VERSION == "v1.0.5"


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
