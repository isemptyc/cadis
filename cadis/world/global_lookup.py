"""Public world-context lookup entrypoint."""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import Any, Optional

from cadis.version import __version__

from .cgd_world_resolver import CGDWorldResolver


class GlobalLookup:
    """Public API for world context lookup only."""

    ENGINE = "cadis.world"
    VERSION = __version__

    def __init__(self, *, world_resolver: Any):
        self._world_resolver = world_resolver

    @classmethod
    def from_defaults(
        cls,
        *,
        cgd_path: Optional[Path] = None,
        cgd_dataset_id: str = "ne.global",
        cgd_dataset_version: Optional[str] = "v0.1.0",
    ) -> "GlobalLookup":
        """Build GlobalLookup with bundled-CGD world resolver."""
        if cgd_path is None:
            bundled = cls._resolve_bundled_cgd_path(
                dataset_id=cgd_dataset_id,
                dataset_version=cgd_dataset_version,
            )
            if bundled is None:
                raise FileNotFoundError(
                    "Bundled CGD dataset not found. "
                    "Provide cgd_path explicitly or install a wheel that includes "
                    f"'{cgd_dataset_id}.{cgd_dataset_version}.cgd'."
                )
            cgd_path = bundled

        world_resolver = CGDWorldResolver(cgd_path=Path(cgd_path))
        return cls(world_resolver=world_resolver)

    @staticmethod
    def _resolve_bundled_cgd_path(*, dataset_id: str, dataset_version: Optional[str]) -> Optional[Path]:
        if dataset_id != "ne.global" or not dataset_version:
            return None
        filename = f"{dataset_id}.{dataset_version}.cgd"
        try:
            candidate = importlib.resources.files("cadis.world").joinpath("data").joinpath(filename)
            if candidate.is_file():
                return Path(candidate)
        except Exception:
            return None
        return None

    def lookup(self, lat: float, lon: float) -> dict[str, Any]:
        """Resolve world context and return a unified envelope."""
        try:
            world_context = self._world_resolver.resolve(lat, lon)
        except Exception as exc:
            return self._failed(
                world_context={"lookup_status": "failed", "error": str(exc)},
                reason="world_runtime_error",
            )

        if world_context.get("lookup_status") != "ok":
            return self._failed(world_context=world_context, reason="world_resolution_failed")

        return {
            "lookup_status": "ok",
            "engine": self.ENGINE,
            "version": self.VERSION,
            "reason": None,
            "world_context": world_context,
        }

    def _failed(self, *, world_context: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "lookup_status": "failed",
            "engine": self.ENGINE,
            "version": self.VERSION,
            "reason": reason,
            "world_context": world_context,
        }
