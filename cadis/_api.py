"""Public API for Cadis SDK/control-layer operations."""

from __future__ import annotations

import json
import math
import os
import re
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable

from ._cache import resolve_cache_dir
from ._country_names import country_name_for_iso2
from ._manager import get_manager
from .types import (
    BootstrapResponse,
    ExecutionOutcome,
    InfoResponse,
    LookupManyResponseItem,
    LookupResponse,
    LookupState,
    WorldClassificationResponse,
    WorldState,
)
from .version import __version__

SCHEMA_VERSION = "1"
VERSION = __version__
SUPPORTED_ISO2 = ["JP", "TW", "GB", "IT", "KR", "SE", "NO", "DK", "BE", "NL"]
OFFSHORE_CANDIDATE_MARGIN_KM = 5.0
OFFSHORE_MAX_CANDIDATES = 5


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


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if not math.isfinite(value) or value < 0:
        return default
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < 1:
        return default
    return value


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


def _failed_classification(
    *,
    state: LookupState,
    result: dict[str, Any] | None = None,
) -> WorldClassificationResponse:
    return {
        "engine": "cadis",
        "version": VERSION,
        "classification_status": "failed",
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
        state: WorldState = {
            "status": "ok",
            "classification": "country",
            "iso2": str(country.get("iso2")).upper(),
        }
        name = country.get("name")
        if isinstance(name, str) and name.strip():
            state["name"] = name.strip()
        else:
            fallback_name = country_name_for_iso2(state["iso2"])
            if fallback_name is not None:
                state["name"] = fallback_name
        return state
    return {
        "status": "ok",
        "classification": "unknown",
    }


def _point_to_bbox_distance_km(
    *,
    lat: float,
    lon: float,
    bbox: tuple[float, float, float, float],
) -> float:
    minx, miny, maxx, maxy = bbox
    clamped_lon = min(max(lon, minx), maxx)
    clamped_lat = min(max(lat, miny), maxy)
    if clamped_lon == lon and clamped_lat == lat:
        return 0.0
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.radians(clamped_lat)
    lon2 = math.radians(clamped_lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2) + math.cos(lat1) * math.cos(lat2) * (
        math.sin(dlon / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _expand_bbox_km(
    bbox: tuple[float, float, float, float],
    *,
    distance_km: float,
) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = bbox
    lat_delta = distance_km / 111.0
    expanded_miny = max(-90.0, miny - lat_delta)
    expanded_maxy = min(90.0, maxy + lat_delta)
    max_abs_lat = min(89.9, max(abs(expanded_miny), abs(expanded_maxy)))
    cos_lat = max(0.01, math.cos(math.radians(max_abs_lat)))
    lon_delta = distance_km / (111.0 * cos_lat)
    return (
        max(-180.0, minx - lon_delta),
        expanded_miny,
        min(180.0, maxx + lon_delta),
        expanded_maxy,
    )


def _load_ffsf_feature_and_part_bboxes(
    ffsf_path: Path,
) -> tuple[list[tuple[int, int]], list[tuple[float, float, float, float]]]:
    with ffsf_path.open("rb") as fh:
        header = fh.read(16)
        if len(header) < 16 or header[0:4] != b"FFSF":
            raise ValueError("Invalid FFSF header")
        version, feature_count, total_part_count = struct.unpack_from("<III", header, 4)
        if version not in {2, 3}:
            raise ValueError(f"Unsupported FFSF version {version}")

        feature_index: list[tuple[int, int]] = []
        for _ in range(feature_count):
            raw = fh.read(16)
            if len(raw) != 16:
                raise ValueError("Invalid FFSF feature index")
            _, _, part_start_idx, part_count = struct.unpack("<4I", raw)
            feature_index.append((part_start_idx, part_count))

        part_bboxes: list[tuple[float, float, float, float]] = []
        for _ in range(total_part_count):
            raw = fh.read(16)
            if len(raw) != 16:
                raise ValueError("Invalid FFSF part bbox table")
            part_bboxes.append(struct.unpack("<4f", raw))

    return feature_index, part_bboxes


def _country_scope_bbox_from_dataset(dataset_dir: str | Path) -> tuple[float, float, float, float] | None:
    root = Path(dataset_dir)
    meta_path = root / "geometry_meta.json"
    ffsf_path = root / "geometry.ffsf"
    if not meta_path.exists() or not ffsf_path.exists():
        return None

    raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(raw_meta, list):
        return None
    feature_index, part_bboxes = _load_ffsf_feature_and_part_bboxes(ffsf_path)
    if len(feature_index) != len(raw_meta):
        return None

    flagged_levels = [
        meta.get("level")
        for meta in raw_meta
        if isinstance(meta, dict) and meta.get("country_scope_flag") is True and isinstance(meta.get("level"), int)
    ]
    target_level = min(flagged_levels) if flagged_levels else None
    use_flagged_scope = target_level is not None

    if target_level is None:
        levels = [
            meta.get("level")
            for meta in raw_meta
            if isinstance(meta, dict) and isinstance(meta.get("level"), int)
        ]
        if not levels:
            return None
        target_level = min(levels)

    selected: list[tuple[float, float, float, float]] = []
    for feature_idx, (part_start_idx, part_count) in enumerate(feature_index):
        meta = raw_meta[feature_idx]
        if not isinstance(meta, dict):
            continue
        if use_flagged_scope and meta.get("country_scope_flag") is not True:
            continue
        if meta.get("level") != target_level:
            continue
        for part_idx in range(part_start_idx, part_start_idx + part_count):
            if 0 <= part_idx < len(part_bboxes):
                selected.append(part_bboxes[part_idx])

    if not selected:
        return None
    return (
        min(b[0] for b in selected),
        min(b[1] for b in selected),
        max(b[2] for b in selected),
        max(b[3] for b in selected),
    )


def _load_offshore_max_distance_km(dataset_dir: str | Path) -> float | None:
    policy_path = Path(dataset_dir) / "runtime_policy.json"
    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    nearby_policy = raw.get("nearby_policy", {})
    if nearby_policy is None:
        nearby_policy = {}
    if not isinstance(nearby_policy, dict):
        return None
    offshore = nearby_policy.get("offshore_max_distance_km", 20.0)
    if offshore is None or not isinstance(offshore, (int, float)):
        return None
    offshore = float(offshore)
    if not math.isfinite(offshore) or offshore <= 0:
        return None
    return offshore


def _parse_version_for_sort(raw: str) -> tuple[int, ...]:
    value = raw.strip()
    if value.startswith("v"):
        value = value[1:]
    parts = value.split(".")
    if not parts or any(not p.isdigit() for p in parts):
        return tuple()
    return tuple(int(p) for p in parts)


def _latest_dataset_dir_for_iso2(
    iso2: str,
    *,
    cache_dir: str | Path | None = None,
) -> Path | None:
    cache_root = resolve_cache_dir() if cache_dir is None else Path(cache_dir).expanduser()
    versions_root = cache_root / iso2 / f"{iso2.lower()}.admin"
    if not versions_root.exists() or not versions_root.is_dir():
        return None

    candidates: list[tuple[tuple[int, ...], Path]] = []
    for child in versions_root.iterdir():
        if not child.is_dir():
            continue
        parsed = _parse_version_for_sort(child.name)
        if parsed:
            candidates.append((parsed, child))
    candidates.sort(reverse=True)
    for _, dataset_dir in candidates:
        required = [
            "dataset_release_manifest.json",
            "geometry.ffsf",
            "geometry_meta.json",
            "runtime_policy.json",
        ]
        if all((dataset_dir / name).exists() for name in required):
            return dataset_dir
    return None


def _offshore_candidate_iso2(
    *,
    manager: Any,
    lat: float,
    lon: float,
    cache_dir: str | Path | None = None,
) -> list[str]:
    max_candidates = _env_int("CADIS_OFFSHORE_MAX_CANDIDATES", OFFSHORE_MAX_CANDIDATES)
    margin_km = _env_float("CADIS_OFFSHORE_CANDIDATE_MARGIN_KM", OFFSHORE_CANDIDATE_MARGIN_KM)

    candidates: list[tuple[float, str]] = []
    for iso2 in _installed_iso2_from_cache(cache_dir=cache_dir):
        if not manager.is_iso2_allowed(iso2):
            continue
        dataset_dir = _latest_dataset_dir_for_iso2(iso2, cache_dir=cache_dir)
        if dataset_dir is None:
            continue

        try:
            offshore_km = _load_offshore_max_distance_km(dataset_dir)
            if offshore_km is None:
                continue
            scope_bbox = _country_scope_bbox_from_dataset(dataset_dir)
        except Exception:
            continue
        if scope_bbox is None:
            continue

        expanded = _expand_bbox_km(
            scope_bbox,
            distance_km=float(offshore_km) + margin_km,
        )
        distance_km = _point_to_bbox_distance_km(lat=lat, lon=lon, bbox=expanded)
        if distance_km > 0.0:
            continue
        candidates.append(
            (
                _point_to_bbox_distance_km(lat=lat, lon=lon, bbox=scope_bbox),
                iso2,
            )
        )

    candidates.sort(key=lambda item: (item[0], item[1]))
    return [iso2 for _, iso2 in candidates[:max_candidates]]


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


def _retry_open_sea_with_candidate_runtime(
    *,
    manager: Any,
    lat: float,
    lon: float,
    cache_dir: str | Path | None = None,
) -> tuple[str, Any] | None:
    nearest: tuple[float, str, Any] | None = None
    for iso2 in _offshore_candidate_iso2(
        manager=manager,
        lat=lat,
        lon=lon,
        cache_dir=cache_dir,
    ):
        runtime_handle, dataset_state = manager.get_runtime_readiness(iso2, cache_dir=cache_dir)
        if runtime_handle is None:
            continue
        if not isinstance(dataset_state, dict) or dataset_state.get("status") != "ready":
            continue
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


def classify_world(
    lat: float,
    lon: float,
    *,
    cache_dir: str | Path | None = None,
    allowed_iso2: Iterable[str] | None = None,
) -> WorldClassificationResponse:
    if not isinstance(lat, (float, int)) or not isinstance(lon, (float, int)):
        return _failed_classification(state={"input": {"status": "invalid"}})
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return _failed_classification(state={"input": {"status": "invalid"}})

    manager = get_manager(cache_dir=cache_dir, allowed_iso2=allowed_iso2)
    try:
        global_lookup = manager.get_or_init_global_lookup()
        world_result = global_lookup.lookup(float(lat), float(lon))
    except Exception:
        return _failed_classification(state={"world": {"status": "failed", "classification": "unknown"}})

    if not isinstance(world_result, dict):
        return _failed_classification(state={"world": {"status": "failed", "classification": "unknown"}})

    world_status = str(world_result.get("lookup_status", "failed"))
    world_context = world_result.get("world_context")
    world_state = _world_state_from_context(world_context, world_status=world_status)

    if world_status != "ok":
        return _failed_classification(state={"world": world_state})

    return {
        "engine": "cadis",
        "version": VERSION,
        "classification_status": "ok",
        "state": {"world": world_state},
        "result": {"world": dict(world_state)},
    }


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
        retried = _retry_open_sea_with_candidate_runtime(
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


def _lookup_many_point_id(point: object, index: int) -> str:
    if isinstance(point, dict):
        raw_id = point.get("id")
        if isinstance(raw_id, str) and raw_id:
            return raw_id
    return str(index)


def _lookup_many_point_coords(point: object) -> tuple[float, float] | None:
    if not isinstance(point, dict):
        return None
    lat = point.get("lat")
    lon = point.get("lon")
    if not isinstance(lat, (float, int)) or not isinstance(lon, (float, int)):
        return None
    return float(lat), float(lon)


def lookup_many(
    points: Iterable[dict[str, object]],
    *,
    cache_dir: str | Path | None = None,
    allowed_iso2: Iterable[str] | None = None,
) -> list[LookupManyResponseItem]:
    rows = list(points)
    results: list[LookupManyResponseItem] = []
    for index, point in enumerate(rows):
        point_id = _lookup_many_point_id(point, index)
        coords = _lookup_many_point_coords(point)
        if coords is None:
            lookup_payload = _failed_output(state={"input": {"status": "invalid"}})
        else:
            lookup_payload = lookup(
                coords[0],
                coords[1],
                cache_dir=cache_dir,
                allowed_iso2=allowed_iso2,
            )
        results.append({"id": point_id, "lookup": lookup_payload})
    return results


def bootstrap(
    iso2: str,
    *,
    cache_dir: str | Path | None = None,
    allowed_iso2: Iterable[str] | None = None,
    dataset_version: str | None = None,
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
            dataset_version=dataset_version,
            force_reinstall=force_reinstall,
            update_to_latest=update_to_latest,
            download_progress=download_progress,
        )
    except Exception as exc:
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
    dataset_version: str | None = None,
    update_to_latest: bool = False,
    download_progress: Callable[[str, int, int | None], None] | None = None,
) -> BootstrapResponse:
    return bootstrap(
        iso2,
        cache_dir=cache_dir,
        allowed_iso2=allowed_iso2,
        dataset_version=dataset_version,
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
