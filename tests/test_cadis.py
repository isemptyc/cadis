from __future__ import annotations

import importlib
import sys
from types import ModuleType


class _FakeLookup:
    def __init__(self) -> None:
        self.calls = []

    def lookup(self, lat: float, lon: float):
        self.calls.append((lat, lon))
        return {
            "lookup_status": "ok",
            "reason": None,
            "world_context": {"iso2": "TW"},
            "admin_result": {"ok": True},
        }


class _FakeGlobalLookup:
    init_calls = 0

    @classmethod
    def from_defaults(cls, **kwargs):
        cls.init_calls += 1
        return _FakeLookup()


def _install_fake_cadis_global(module: ModuleType) -> None:
    sys.modules["cadis_global"] = module


def _reload_cadis_modules() -> None:
    for name in ["cadis", "cadis._api", "cadis._manager"]:
        sys.modules.pop(name, None)


def test_lookup_is_lazy_singleton(monkeypatch):
    fake_mod = ModuleType("cadis_global")
    fake_mod.GlobalLookup = _FakeGlobalLookup

    _install_fake_cadis_global(fake_mod)
    _reload_cadis_modules()

    cadis = importlib.import_module("cadis")
    assert _FakeGlobalLookup.init_calls == 0

    first = cadis.lookup(25.03, 121.56)
    second = cadis.lookup(35.68, 139.76)

    assert _FakeGlobalLookup.init_calls == 1
    assert first["lookup_status"] == "ok"
    assert second["lookup_status"] == "ok"


def test_info_has_no_lookup_side_effect(monkeypatch, tmp_path):
    class _NoInitGlobalLookup:
        @classmethod
        def from_defaults(cls, **kwargs):
            raise AssertionError("from_defaults must not be called by info()")

    fake_mod = ModuleType("cadis_global")
    fake_mod.GlobalLookup = _NoInitGlobalLookup
    fake_mod.SUPPORTED_ISO2 = ["tw", "jp"]

    cache_dir = tmp_path / "cadis-cache"
    cache_dir.mkdir()
    (cache_dir / "tw").mkdir()
    (cache_dir / "not-iso").mkdir()
    monkeypatch.setenv("CADIS_CACHE_DIR", str(cache_dir))

    _install_fake_cadis_global(fake_mod)
    _reload_cadis_modules()

    cadis = importlib.import_module("cadis")
    payload = cadis.info()

    assert payload["schema_version"] == "1"
    assert payload["system_iso2"] == ["JP", "TW"]
    assert payload["offline_iso2"] == ["TW"]


def test_reason_normalization_runtime_error(monkeypatch):
    class _BrokenGlobalLookup:
        @classmethod
        def from_defaults(cls, **kwargs):
            raise Exception("boom")

    fake_mod = ModuleType("cadis_global")
    fake_mod.GlobalLookup = _BrokenGlobalLookup

    _install_fake_cadis_global(fake_mod)
    _reload_cadis_modules()

    cadis = importlib.import_module("cadis")
    payload = cadis.lookup(25.03, 121.56)

    assert payload["lookup_status"] == "failed"
    assert payload["reason"] in {"global_init_failed", "internal_error"}
    assert "traceback" not in str(payload).lower()
