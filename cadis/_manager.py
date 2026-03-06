"""Control-layer manager for integrated Cadis execution."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ._cache import resolve_cache_dir
from ._errors import normalize_reason
from ._policy import DatasetPolicy, load_dataset_policy_from_env


@dataclass
class _RuntimeHandle:
    runtime: Any
    dataset_dir: str
    dataset_state: dict[str, Any]


class CadisManager:
    """Process-level manager for world + runtime orchestration."""

    def __init__(self, *, dataset_policy: DatasetPolicy | None = None) -> None:
        self._global_lookup = None
        self._runtime_handles: dict[str, _RuntimeHandle] = {}
        self._lock = threading.Lock()
        self._dataset_policy = dataset_policy or load_dataset_policy_from_env()

    def is_initialized(self) -> bool:
        return self._global_lookup is not None

    @property
    def dataset_policy(self) -> DatasetPolicy:
        return self._dataset_policy

    def _blocked_dataset_state(self, iso2: str) -> dict[str, Any]:
        return {
            "status": "blocked",
            "iso2": iso2,
            "detail_code": "dataset_blocked_by_policy",
        }

    def is_iso2_allowed(self, iso2: str) -> bool:
        return self._dataset_policy.allows(iso2)

    def get_or_init_global_lookup(self):
        if self._global_lookup is not None:
            return self._global_lookup

        with self._lock:
            if self._global_lookup is not None:
                return self._global_lookup

            try:
                from cadis.world import GlobalLookup
            except Exception as exc:  # pragma: no cover - exercised via tests with import stubs
                raise ImportError(normalize_reason(exc)) from None

            try:
                self._global_lookup = GlobalLookup.from_defaults()
            except Exception as exc:
                raise RuntimeError(normalize_reason(exc)) from None

            return self._global_lookup

    @staticmethod
    def _dataset_id_for_iso2(iso2: str) -> str:
        return f"{iso2.lower()}.admin"

    @staticmethod
    def _resolve_cache_root(cache_dir: str | Path | None = None) -> Path:
        if cache_dir is None:
            return resolve_cache_dir()
        return Path(cache_dir).expanduser()

    def _versions_root(self, iso2: str, *, cache_dir: str | Path | None = None) -> Path:
        cache_dir = self._resolve_cache_root(cache_dir)
        return cache_dir / iso2 / self._dataset_id_for_iso2(iso2)

    def _find_local_ready_dataset(
        self,
        iso2: str,
        *,
        cache_dir: str | Path | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        from cadis.runtime import inspect_dataset
        try:
            from cadis.cdn import parse_version_for_sort
        except Exception:
            def parse_version_for_sort(raw: str) -> tuple[int, ...]:
                value = raw.strip()
                if value.startswith("v"):
                    value = value[1:]
                parts = value.split(".")
                if not parts or any(not p.isdigit() for p in parts):
                    return tuple()
                return tuple(int(p) for p in parts)

        versions_root = self._versions_root(iso2, cache_dir=cache_dir)
        if not versions_root.exists() or not versions_root.is_dir():
            return None, {"status": "missing"}

        candidates: list[tuple[tuple[int, ...], Path]] = []
        for child in versions_root.iterdir():
            if not child.is_dir():
                continue
            parsed = parse_version_for_sort(child.name)
            if parsed:
                candidates.append((parsed, child))
        candidates.sort(reverse=True)

        for _, dataset_dir in candidates:
            inspection = inspect_dataset(dataset_dir)
            state = inspection.get("state", {}).get("dataset", {})
            status = state.get("status")
            if status == "ready":
                return str(dataset_dir), {
                    "status": "ready",
                    "dataset_dir": str(dataset_dir),
                }

        if candidates:
            return None, {"status": "invalid"}
        return None, {"status": "missing"}

    def _create_runtime_handle_from_dataset_dir(self, iso2: str, dataset_dir: str) -> _RuntimeHandle:
        from cadis.runtime import CadisRuntime

        runtime = CadisRuntime(dataset_dir=dataset_dir)
        return _RuntimeHandle(
            runtime=runtime,
            dataset_dir=dataset_dir,
            dataset_state={
                "status": "ready",
                "iso2": iso2,
                "dataset_dir": dataset_dir,
            },
        )

    def get_runtime_if_ready(self, iso2: str) -> _RuntimeHandle | None:
        handle, _ = self.get_runtime_readiness(iso2)
        return handle

    def get_runtime_readiness(self, iso2: str) -> tuple[_RuntimeHandle | None, dict[str, Any]]:
        normalized_iso2 = iso2.strip().upper()
        if not self.is_iso2_allowed(normalized_iso2):
            return None, self._blocked_dataset_state(normalized_iso2)
        handle = self._runtime_handles.get(normalized_iso2)
        if handle is not None:
            return handle, dict(handle.dataset_state)

        with self._lock:
            handle = self._runtime_handles.get(normalized_iso2)
            if handle is not None:
                return handle, dict(handle.dataset_state)
            dataset_dir, state = self._find_local_ready_dataset(normalized_iso2)
            if dataset_dir is None:
                state_with_iso2 = dict(state)
                state_with_iso2.setdefault("iso2", normalized_iso2)
                return None, state_with_iso2
            handle = self._create_runtime_handle_from_dataset_dir(normalized_iso2, dataset_dir)
            handle.dataset_state.update(state)
            self._runtime_handles[normalized_iso2] = handle
            return handle, dict(handle.dataset_state)

    def bootstrap_runtime(
        self,
        iso2: str,
        *,
        cache_dir: str | Path | None = None,
        force_reinstall: bool = False,
        update_to_latest: bool = False,
        download_progress: Callable[[str, int, int | None], None] | None = None,
    ) -> dict[str, Any]:
        from cadis.cdn import install_dataset
        from cadis.runtime import bootstrap_dataset

        normalized_iso2 = iso2.strip().upper()
        if not self.is_iso2_allowed(normalized_iso2):
            return {
                "bootstrap_status": "failed",
                "state": {"dataset": self._blocked_dataset_state(normalized_iso2)},
            }
        cache_root = self._resolve_cache_root(cache_dir)
        install_state = install_dataset(
            iso2=normalized_iso2,
            cache_root=cache_root,
            update_to_latest=update_to_latest,
            force_reinstall=force_reinstall,
            download_progress=download_progress,
        )
        dataset_dir = install_state.get("dataset_dir")
        if not isinstance(dataset_dir, str) or not dataset_dir.strip():
            return {"bootstrap_status": "failed", "state": {"dataset": {"status": "missing"}}}

        bootstrap_state = bootstrap_dataset(dataset_dir)
        status = bootstrap_state.get("bootstrap_status")
        if status != "ready":
            return {
                "bootstrap_status": "failed",
                "state": bootstrap_state.get("state", {"dataset": {"status": "invalid"}}),
            }

        handle = self._create_runtime_handle_from_dataset_dir(normalized_iso2, dataset_dir)
        with self._lock:
            self._runtime_handles[normalized_iso2] = handle

        return {
            "bootstrap_status": "ready",
            "state": {
                "dataset": {
                    "status": "ready",
                    "iso2": normalized_iso2,
                    "dataset_dir": dataset_dir,
                }
            },
            "dataset": install_state,
        }


_MANAGER = CadisManager()


def get_manager() -> CadisManager:
    return _MANAGER
