"""SDK surface for explicit programmatic Cadis interaction."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ._api import (
    bootstrap,
    classify_world,
    clear_runtimes,
    info,
    lookup,
    lookup_many,
    memory_report,
    reinstall,
)
from .types import (
    BootstrapResponse,
    InfoResponse,
    LookupManyPoint,
    LookupManyResponseItem,
    LookupResponse,
    WorldClassificationResponse,
)


class CadisSDK:
    """Explicit SDK wrapper with no implicit remediation behavior."""

    def __init__(
        self,
        *,
        cache_dir: str | Path | None = None,
        allowed_iso2: Iterable[str] | None = None,
    ) -> None:
        self._cache_dir = cache_dir
        self._allowed_iso2 = tuple(allowed_iso2) if allowed_iso2 is not None else None

    def _cache_dir_or_default(self, cache_dir: str | Path | None) -> str | Path | None:
        return self._cache_dir if cache_dir is None else cache_dir

    def _allowed_iso2_or_default(
        self,
        allowed_iso2: Iterable[str] | None,
    ) -> Iterable[str] | None:
        return self._allowed_iso2 if allowed_iso2 is None else allowed_iso2

    def lookup(
        self,
        lat: float,
        lon: float,
        *,
        cache_dir: str | Path | None = None,
        allowed_iso2: Iterable[str] | None = None,
    ) -> LookupResponse:
        return lookup(
            lat,
            lon,
            cache_dir=self._cache_dir_or_default(cache_dir),
            allowed_iso2=self._allowed_iso2_or_default(allowed_iso2),
        )

    def lookup_many(
        self,
        points: Iterable[LookupManyPoint],
        *,
        cache_dir: str | Path | None = None,
        allowed_iso2: Iterable[str] | None = None,
        runtime_cache_policy: str | None = None,
    ) -> list[LookupManyResponseItem]:
        return lookup_many(
            points,
            cache_dir=self._cache_dir_or_default(cache_dir),
            allowed_iso2=self._allowed_iso2_or_default(allowed_iso2),
            runtime_cache_policy=runtime_cache_policy,
        )

    def classify_world(
        self,
        lat: float,
        lon: float,
        *,
        cache_dir: str | Path | None = None,
        allowed_iso2: Iterable[str] | None = None,
    ) -> WorldClassificationResponse:
        return classify_world(
            lat,
            lon,
            cache_dir=self._cache_dir_or_default(cache_dir),
            allowed_iso2=self._allowed_iso2_or_default(allowed_iso2),
        )

    def bootstrap(
        self,
        iso2: str,
        *,
        cache_dir: str | Path | None = None,
        allowed_iso2: Iterable[str] | None = None,
        dataset_version: str | None = None,
        force_reinstall: bool = False,
        update_to_latest: bool = False,
    ) -> BootstrapResponse:
        return bootstrap(
            iso2,
            cache_dir=self._cache_dir_or_default(cache_dir),
            allowed_iso2=self._allowed_iso2_or_default(allowed_iso2),
            dataset_version=dataset_version,
            force_reinstall=force_reinstall,
            update_to_latest=update_to_latest,
        )

    def reinstall(
        self,
        iso2: str,
        *,
        cache_dir: str | Path | None = None,
        allowed_iso2: Iterable[str] | None = None,
        dataset_version: str | None = None,
        update_to_latest: bool = False,
    ) -> BootstrapResponse:
        return reinstall(
            iso2,
            cache_dir=self._cache_dir_or_default(cache_dir),
            allowed_iso2=self._allowed_iso2_or_default(allowed_iso2),
            dataset_version=dataset_version,
            update_to_latest=update_to_latest,
        )

    def info(
        self,
        *,
        cache_dir: str | Path | None = None,
        allowed_iso2: Iterable[str] | None = None,
    ) -> InfoResponse:
        return info(
            cache_dir=self._cache_dir_or_default(cache_dir),
            allowed_iso2=self._allowed_iso2_or_default(allowed_iso2),
        )

    def memory_report(
        self,
        *,
        cache_dir: str | Path | None = None,
        allowed_iso2: Iterable[str] | None = None,
    ) -> dict[str, object]:
        return memory_report(
            cache_dir=self._cache_dir_or_default(cache_dir),
            allowed_iso2=self._allowed_iso2_or_default(allowed_iso2),
        )

    def clear_runtimes(
        self,
        *,
        cache_dir: str | Path | None = None,
        allowed_iso2: Iterable[str] | None = None,
    ) -> int:
        return clear_runtimes(
            cache_dir=self._cache_dir_or_default(cache_dir),
            allowed_iso2=self._allowed_iso2_or_default(allowed_iso2),
        )
