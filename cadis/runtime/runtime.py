from __future__ import annotations

from pathlib import Path
from typing import cast

from cadis.runtime.execution.pipeline import CadisLookupPipeline
from cadis.runtime.types import LookupResponse


class CadisRuntime:
    """Stable public runtime entrypoint for country-level lookup execution."""

    def __init__(self, *, dataset_dir: str | Path, country_name: str | None = None):
        self._pipeline = CadisLookupPipeline(dataset_dir=dataset_dir, country_name=country_name)

    def lookup(self, lat: float, lon: float) -> LookupResponse:
        return cast(LookupResponse, self._pipeline.lookup(lat, lon))
