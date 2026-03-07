"""Control-layer manager for integrated Cadis execution."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from ._cache import resolve_cache_dir
from ._errors import normalize_reason
from ._policy import DatasetPolicy, load_dataset_policy_from_env, make_dataset_policy


@dataclass
class _RuntimeHandle:
    runtime: Any
    dataset_dir: str
    dataset_state: dict[str, Any]


class CadisManager:
    """Process-level manager for world + runtime orchestration."""

    def __init__(
        self,
        *,
        dataset_policy: DatasetPolicy | None = None,
        default_cache_dir: str | Path | None = None,
    ) -> None:
        self._global_lookup = None
        self._runtime_handles: dict[str, _RuntimeHandle] = {}
        self._lock = threading.Lock()
        self._dataset_policy = dataset_policy or load_dataset_policy_from_env()
        self._default_cache_dir = (
            Path(default_cache_dir).expanduser() if default_cache_dir is not None else None
        )

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

    def _invalid_dataset_state(
        self,
        iso2: str,
        *,
        detail_code: str,
        detail: str,
        dataset_dir: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state: dict[str, Any] = {
            "status": "invalid",
            "iso2": iso2,
            "detail_code": detail_code,
            "detail": detail,
        }
        if dataset_dir:
            state["dataset_dir"] = dataset_dir
        if details:
            state["details"] = details
        return state

    @staticmethod
    def _classify_install_failure(exc: Exception) -> str:
        message = str(exc).lower()
        if "http error" in message or "urlopen error" in message or "timed out" in message:
            return "download_failed"
        if "dataset_manifest" in message or "release manifest" in message or "manifest" in message:
            return "release_manifest_invalid"
        if "missing required files" in message or "missing after bootstrap download" in message:
            return "dataset_dir_incomplete"
        if "runtime" in message and "supported" in message:
            return "release_runtime_incompatible"
        return "install_failed"

    @staticmethod
    def _augment_dataset_state(
        state: dict[str, Any],
        *,
        iso2: str,
        dataset_dir: str | None = None,
        fallback_detail_code: str | None = None,
        fallback_detail: str | None = None,
    ) -> dict[str, Any]:
        out = dict(state)
        out.setdefault("iso2", iso2)
        if dataset_dir:
            out.setdefault("dataset_dir", dataset_dir)
        if fallback_detail_code:
            out.setdefault("detail_code", fallback_detail_code)
        if fallback_detail:
            out.setdefault("detail", fallback_detail)
        return out

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

    def _resolve_cache_root(self, cache_dir: str | Path | None = None) -> Path:
        if cache_dir is None:
            if self._default_cache_dir is not None:
                return self._default_cache_dir
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

    def get_runtime_if_ready(
        self,
        iso2: str,
        *,
        cache_dir: str | Path | None = None,
    ) -> _RuntimeHandle | None:
        handle, _ = self.get_runtime_readiness(iso2, cache_dir=cache_dir)
        return handle

    def get_runtime_readiness(
        self,
        iso2: str,
        *,
        cache_dir: str | Path | None = None,
    ) -> tuple[_RuntimeHandle | None, dict[str, Any]]:
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
            dataset_dir, state = self._find_local_ready_dataset(normalized_iso2, cache_dir=cache_dir)
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
        try:
            install_state = install_dataset(
                iso2=normalized_iso2,
                cache_root=cache_root,
                update_to_latest=update_to_latest,
                force_reinstall=force_reinstall,
                download_progress=download_progress,
            )
        except Exception as exc:
            detail_code = self._classify_install_failure(exc)
            return {
                "bootstrap_status": "failed",
                "state": {
                    "dataset": self._invalid_dataset_state(
                        normalized_iso2,
                        detail_code=detail_code,
                        detail=str(exc),
                        details={
                            "exception_type": exc.__class__.__name__,
                            "cache_dir": str(cache_root),
                        },
                    )
                },
            }
        dataset_dir = install_state.get("dataset_dir")
        if not isinstance(dataset_dir, str) or not dataset_dir.strip():
            return {
                "bootstrap_status": "failed",
                "state": {
                    "dataset": {
                        "status": "missing",
                        "iso2": normalized_iso2,
                        "detail_code": "install_missing_dataset_dir",
                        "detail": "Dataset install completed without a dataset_dir.",
                    }
                },
            }

        bootstrap_state = bootstrap_dataset(dataset_dir)
        status = bootstrap_state.get("bootstrap_status")
        if status != "ready":
            raw_state = bootstrap_state.get("state", {"dataset": {"status": "invalid"}})
            dataset_state = raw_state.get("dataset", {})
            if not isinstance(dataset_state, dict):
                dataset_state = {"status": "invalid"}
            return {
                "bootstrap_status": "failed",
                "state": {
                    "dataset": self._augment_dataset_state(
                        dataset_state,
                        iso2=normalized_iso2,
                        dataset_dir=dataset_dir,
                        fallback_detail_code="bootstrap_failed",
                        fallback_detail="Dataset bootstrap did not produce a ready runtime.",
                    )
                },
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


_MANAGERS: dict[tuple[str, tuple[str, ...]], CadisManager] = {}
_MANAGERS_LOCK = threading.Lock()


def get_manager(
    *,
    cache_dir: str | Path | None = None,
    allowed_iso2: Iterable[str] | None = None,
) -> CadisManager:
    resolved_cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else resolve_cache_dir()
    if allowed_iso2 is None:
        dataset_policy = load_dataset_policy_from_env()
    else:
        dataset_policy = make_dataset_policy(allowed_iso2)

    key = (
        str(resolved_cache_dir),
        tuple(sorted(dataset_policy.allowed_iso2)),
    )
    manager = _MANAGERS.get(key)
    if manager is not None:
        return manager

    with _MANAGERS_LOCK:
        manager = _MANAGERS.get(key)
        if manager is not None:
            return manager
        manager = CadisManager(
            dataset_policy=dataset_policy,
            default_cache_dir=resolved_cache_dir,
        )
        _MANAGERS[key] = manager
        return manager
