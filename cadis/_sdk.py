"""SDK surface for explicit programmatic Cadis interaction."""

from __future__ import annotations

from pathlib import Path

from ._api import bootstrap, info, lookup, reinstall
from .types import BootstrapResponse, InfoResponse, LookupResponse


class CadisSDK:
    """Explicit SDK wrapper with no implicit remediation behavior."""

    def lookup(self, lat: float, lon: float) -> LookupResponse:
        return lookup(lat, lon)

    def bootstrap(
        self,
        iso2: str,
        *,
        cache_dir: str | Path | None = None,
        force_reinstall: bool = False,
        update_to_latest: bool = False,
    ) -> BootstrapResponse:
        return bootstrap(
            iso2,
            cache_dir=cache_dir,
            force_reinstall=force_reinstall,
            update_to_latest=update_to_latest,
        )

    def reinstall(
        self,
        iso2: str,
        *,
        cache_dir: str | Path | None = None,
        update_to_latest: bool = False,
    ) -> BootstrapResponse:
        return reinstall(iso2, cache_dir=cache_dir, update_to_latest=update_to_latest)

    def info(self) -> InfoResponse:
        return info()
