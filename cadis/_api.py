"""Public API for Cadis SDK/control-layer operations."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable

from ._cache import resolve_cache_dir
from ._manager import get_manager
from .types import BootstrapResponse, ExecutionOutcome, InfoResponse, LookupResponse, LookupState, WorldState
from .version import __version__

SCHEMA_VERSION = "1"
VERSION = __version__
SUPPORTED_ISO2 = ["JP", "TW", "GB", "IT"]


def _infer_resolution_state(
    *,
    lookup_status: str,
    state: LookupState,
) -> str:
    if lookup_status == "ok":
        return "resolved"
    if lookup_status == "partial":
        return "partial"

    input_state = state.get("input")
    if isinstance(input_state, dict) and input_state.get("status") == "invalid":
        return "invalid_input"

    dataset_state = state.get("dataset")
    if isinstance(dataset_state, dict):
        dataset_status = dataset_state.get("status")
        if dataset_status == "blocked":
            return "blocked_by_policy"
        if dataset_status in {"missing", "invalid"}:
            return "remediable_capability_gap"
        if dataset_status == "ready":
            return "unresolved_country"

    world_state = state.get("world")
    if isinstance(world_state, dict):
        if world_state.get("status") == "failed":
            return "engine_failure"
        classification = world_state.get("classification")
        if isinstance(classification, str) and classification and classification != "country":
            return "terminal_non_country"

    return "engine_failure"


def _infer_capability_detail(*, lookup_status: str, state: LookupState) -> str | None:
    if lookup_status == "ok":
        return None
    if lookup_status == "partial":
        return None

    input_state = state.get("input")
    if isinstance(input_state, dict) and input_state.get("status") == "invalid":
        return "input_invalid"

    dataset_state = state.get("dataset")
    if isinstance(dataset_state, dict):
        dataset_status = dataset_state.get("status")
        iso2 = dataset_state.get("iso2")
        if dataset_status == "blocked":
            return "dataset_blocked_by_policy"
        if dataset_status == "invalid":
            return "dataset_invalid"
        if dataset_status == "ready":
            return "dataset_ready_unresolved"
        if dataset_status == "missing":
            if isinstance(iso2, str) and iso2.upper() in SUPPORTED_ISO2:
                return "supported_dataset_missing"
            return "unsupported_country"

    world_state = state.get("world")
    if isinstance(world_state, dict):
        classification = world_state.get("classification")
        if isinstance(classification, str) and classification and classification != "country":
            return "non_country_world_classification"

    return None


def _execution_outcome(*, lookup_status: str, state: LookupState) -> ExecutionOutcome:
    outcome: ExecutionOutcome = {
        "lookup_status": lookup_status,  # type: ignore[typeddict-item]
        "resolution_state": _infer_resolution_state(lookup_status=lookup_status, state=state),  # type: ignore[typeddict-item]
    }
    capability_detail = _infer_capability_detail(lookup_status=lookup_status, state=state)
    if capability_detail is not None:
        outcome["capability_detail"] = capability_detail  # type: ignore[typeddict-item]
    return outcome


def _installed_iso2_from_cache(cache_dir: str | Path | None = None) -> list[str]:
    path = resolve_cache_dir() if cache_dir is None else Path(cache_dir).expanduser()
    if not path.exists() or not path.is_dir():
        return []

    iso2: list[str] = []
    for child in path.iterdir():
        if child.is_dir() and re.fullmatch(r"[A-Za-z]{2}", child.name):
            iso2.append(child.name.upper())

    return sorted(set(iso2))


def _failed_output(
    *,
    state: LookupState,
    result: dict[str, Any] | None = None,
) -> LookupResponse:
    return {
        "engine": "cadis",
        "version": VERSION,
        "execution": _execution_outcome(lookup_status="failed", state=state),
        "state": state,
        "result": result,
    }


def _extract_iso2(world_context: Any) -> str | None:
    if not isinstance(world_context, dict):
        return None
    country = world_context.get("country")
    if not isinstance(country, dict):
        return None
    iso2 = country.get("iso2")
    if not isinstance(iso2, str) or len(iso2.strip()) != 2:
        return None
    return iso2.strip().upper()


def _world_state_from_context(world_context: Any, *, world_status: str) -> WorldState:
    if world_status != "ok":
        return {
            "status": "failed",
            "classification": "unknown",
        }
    if not isinstance(world_context, dict):
        return {
            "status": "failed",
            "classification": "unknown",
        }

    world_result = world_context.get("world_result")
    if isinstance(world_result, dict):
        world_type = world_result.get("type")
        if isinstance(world_type, str) and world_type:
            state: WorldState = {
                "status": "ok",
                "classification": world_type,
            }
            name = world_result.get("name")
            if isinstance(name, str) and name.strip():
                state["name"] = name.strip()
            return state
    country = world_context.get("country")
    if isinstance(country, dict) and isinstance(country.get("iso2"), str):
        return {
            "status": "ok",
            "classification": "country",
            "iso2": str(country.get("iso2")).upper(),
        }
    return {
        "status": "ok",
        "classification": "unknown",
    }


def _ready_runtime_handles_from_cache(
    manager: Any,
    *,
    cache_dir: str | Path | None = None,
) -> list[tuple[str, Any]]:
    handles: list[tuple[str, Any]] = []
    for iso2 in _installed_iso2_from_cache(cache_dir=cache_dir):
        runtime_handle, dataset_state = manager.get_runtime_readiness(iso2, cache_dir=cache_dir)
        if runtime_handle is None:
            continue
        if not isinstance(dataset_state, dict) or dataset_state.get("status") != "ready":
            continue
        handles.append((iso2, runtime_handle))
    return handles


def _runtime_offshore_distance_km(runtime_handle: Any, *, lat: float, lon: float) -> float | None:
    runtime = getattr(runtime_handle, "runtime", None)
    pipeline = getattr(runtime, "_pipeline", None)
    if pipeline is None:
        return None

    geometry_index = getattr(pipeline, "geometry_index", None)
    policy = getattr(pipeline, "policy", None)
    if geometry_index is None or policy is None:
        return None
    if not geometry_index.has_country_scope_geometry():
        return None

    offshore_km = getattr(policy, "offshore_max_distance_km", None)
    if offshore_km is None:
        return None

    pt = SimpleNamespace(x=float(lon), y=float(lat))
    return float(geometry_index.distance_km_to_country_scope(pt))


def _retry_open_sea_with_installed_runtime(
    *,
    manager: Any,
    lat: float,
    lon: float,
    cache_dir: str | Path | None = None,
) -> tuple[str, Any] | None:
    nearest: tuple[float, str, Any] | None = None
    for iso2, runtime_handle in _ready_runtime_handles_from_cache(manager, cache_dir=cache_dir):
        distance_km = _runtime_offshore_distance_km(runtime_handle, lat=lat, lon=lon)
        if distance_km is None:
            continue

        pipeline = getattr(getattr(runtime_handle, "runtime", None), "_pipeline", None)
        policy = getattr(pipeline, "policy", None)
        offshore_km = getattr(policy, "offshore_max_distance_km", None)
        if offshore_km is None or distance_km > float(offshore_km):
            continue

        if nearest is None or distance_km < nearest[0]:
            nearest = (distance_km, iso2, runtime_handle)

    if nearest is None:
        return None
    return nearest[1], nearest[2]


def lookup(
    lat: float,
    lon: float,
    *,
    cache_dir: str | Path | None = None,
    allowed_iso2: Iterable[str] | None = None,
) -> LookupResponse:
    if not isinstance(lat, (float, int)) or not isinstance(lon, (float, int)):
        return _failed_output(state={"input": {"status": "invalid"}})
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return _failed_output(state={"input": {"status": "invalid"}})

    manager = get_manager(cache_dir=cache_dir, allowed_iso2=allowed_iso2)
    try:
        global_lookup = manager.get_or_init_global_lookup()
        world_result = global_lookup.lookup(float(lat), float(lon))
    except Exception:
        return _failed_output(state={"world": {"status": "failed", "classification": "unknown"}})

    if not isinstance(world_result, dict):
        return _failed_output(state={"world": {"status": "failed", "classification": "unknown"}})

    world_status = str(world_result.get("lookup_status", "failed"))
    world_context = world_result.get("world_context")
    world_state = _world_state_from_context(world_context, world_status=world_status)

    if world_status != "ok":
        return _failed_output(state={"world": world_state})

    iso2 = _extract_iso2(world_context)
    if iso2 is None and world_state.get("classification") == "open_sea":
        retried = _retry_open_sea_with_installed_runtime(
            manager=manager,
            lat=float(lat),
            lon=float(lon),
            cache_dir=cache_dir,
        )
        if retried is not None:
            iso2, _ = retried
            world_state = {
                "status": "ok",
                "classification": "country",
                "iso2": iso2,
            }
    if iso2 is None:
        return _failed_output(state={"world": world_state})

    try:
        runtime_handle, dataset_state = manager.get_runtime_readiness(iso2, cache_dir=cache_dir)
    except Exception:
        return _failed_output(
            state={
                "world": world_state,
                "dataset": {"status": "invalid", "iso2": iso2},
            },
        )
    if runtime_handle is None:
        return _failed_output(
            state={
                "world": world_state,
                "dataset": dataset_state,
            },
        )

    try:
        admin_result = runtime_handle.runtime.lookup(float(lat), float(lon))
    except Exception:
        return _failed_output(
            state={"world": world_state, "dataset": runtime_handle.dataset_state},
        )

    if not isinstance(admin_result, dict):
        return _failed_output(
            state={"world": world_state, "dataset": runtime_handle.dataset_state},
        )

    runtime_status = str(admin_result.get("lookup_status", "failed"))
    if runtime_status not in {"ok", "partial", "failed"}:
        runtime_status = "failed"

    return {
        "engine": "cadis",
        "version": VERSION,
        "execution": _execution_outcome(
            lookup_status=runtime_status,
            state={
                "world": world_state,
                "dataset": runtime_handle.dataset_state,
            },
        ),
        "state": {
            "world": world_state,
            "dataset": runtime_handle.dataset_state,
        },
        "result": admin_result.get("result"),
    }


def bootstrap(
    iso2: str,
    *,
    cache_dir: str | Path | None = None,
    allowed_iso2: Iterable[str] | None = None,
    force_reinstall: bool = False,
    update_to_latest: bool = False,
    download_progress: Callable[[str, int, int | None], None] | None = None,
) -> BootstrapResponse:
    if not isinstance(iso2, str) or len(iso2.strip()) != 2:
        return {
            "engine": "cadis",
            "version": VERSION,
            "bootstrap_status": "failed",
            "state": {"input": {"status": "invalid"}},
        }

    manager = get_manager(cache_dir=cache_dir, allowed_iso2=allowed_iso2)
    try:
        payload = manager.bootstrap_runtime(
            iso2,
            cache_dir=cache_dir,
            force_reinstall=force_reinstall,
            update_to_latest=update_to_latest,
            download_progress=download_progress,
        )
    except Exception:
        return {
            "engine": "cadis",
            "version": VERSION,
            "bootstrap_status": "failed",
            "state": {
                "dataset": {
                    "status": "invalid",
                    "iso2": iso2.strip().upper(),
                    "detail_code": "bootstrap_runtime_exception",
                    "detail": str(exc),
                    "details": {
                        "exception_type": exc.__class__.__name__,
                    },
                }
            },
        }

    return {
        "engine": "cadis",
        "version": VERSION,
        **payload,
    }


def reinstall(
    iso2: str,
    *,
    cache_dir: str | Path | None = None,
    allowed_iso2: Iterable[str] | None = None,
    update_to_latest: bool = False,
    download_progress: Callable[[str, int, int | None], None] | None = None,
) -> BootstrapResponse:
    return bootstrap(
        iso2,
        cache_dir=cache_dir,
        allowed_iso2=allowed_iso2,
        force_reinstall=True,
        update_to_latest=update_to_latest,
        download_progress=download_progress,
    )


def info(
    *,
    cache_dir: str | Path | None = None,
    allowed_iso2: Iterable[str] | None = None,
) -> InfoResponse:
    installed_iso2 = _installed_iso2_from_cache(cache_dir=cache_dir)
    dataset_policy = get_manager(cache_dir=cache_dir, allowed_iso2=allowed_iso2).dataset_policy
    return {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "supported_iso2": list(SUPPORTED_ISO2),
        "installed_iso2": installed_iso2,
        "dataset_lockdown_enabled": dataset_policy.enabled,
        "allowed_iso2": sorted(dataset_policy.allowed_iso2),
    }
