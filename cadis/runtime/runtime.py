from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, cast

from cadis.runtime.execution.pipeline import CadisLookupPipeline
from cadis.runtime.types import LookupResponse


class CadisRuntime:
    """Stable public runtime entrypoint for country-level lookup execution."""

    def __init__(self, *, dataset_dir: str | Path, country_name: str | None = None):
        self._pipeline = CadisLookupPipeline(dataset_dir=dataset_dir, country_name=country_name)

    def lookup(self, lat: float, lon: float) -> LookupResponse:
        return cast(LookupResponse, self._pipeline.lookup(lat, lon))

    def lookup_many(self, points: Iterable[object]) -> list[LookupResponse]:
        return [cast(LookupResponse, item) for item in self._pipeline.lookup_many(points)]

    def memory_report(self) -> dict[str, Any]:
        return self._pipeline.memory_report()
