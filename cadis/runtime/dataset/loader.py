from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cadis.runtime.dataset.ffsf_runtime import FFSFSpatialIndexV3
from cadis.runtime.errors import DatasetNotBootstrappedError, RuntimePolicyInvalidError

@dataclass(frozen=True)
class OptionalLayerDeclaration:
    name: str
    file: str
    type: str
    stage: str
    deterministic: bool


@dataclass(frozen=True)
class RuntimePolicy:
    runtime_policy_version: str
    allowed_levels: list[int]
    allowed_shapes: set[tuple[int, ...]]
    shape_status_map: dict[tuple[int, ...], str]
    hierarchy_parent_level: int
    hierarchy_child_levels: set[int]
    repair_parent_level: int
    repair_child_levels: set[int]
    hierarchy_required: bool
    repair_required: bool
    nearby_fallback_enabled: bool
    nearby_max_distance_km: float | None
    offshore_max_distance_km: float | None
    optional_layers: tuple[OptionalLayerDeclaration, ...]


def _as_int_list(
    value: object,
    *,
    field: str,
    dataset_dir: Path,
    allow_empty: bool = False,
) -> list[int]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(dataset_dir),
            reason=f"{field} must be a non-empty list.",
        )
    out: list[int] = []
    for item in value:
        if not isinstance(item, int):
            raise RuntimePolicyInvalidError(
                dataset_dir=str(dataset_dir),
                reason=f"{field} entries must be integers.",
            )
        if item not in out:
            out.append(item)
    return out


def load_runtime_policy(dataset_dir: str | Path) -> RuntimePolicy:
    root = Path(dataset_dir)
    policy_path = root / "runtime_policy.json"
    if not policy_path.exists():
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="runtime_policy.json is missing.",
        )
    try:
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason=f"runtime_policy.json is malformed JSON: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="runtime_policy.json must be a JSON object.",
        )

    version = raw.get("runtime_policy_version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="runtime_policy_version is required.",
        )

    allowed_levels = _as_int_list(raw.get("allowed_levels"), field="allowed_levels", dataset_dir=root)
    allowed_set = set(allowed_levels)

    allowed_shapes_raw = raw.get("allowed_shapes")
    if not isinstance(allowed_shapes_raw, list) or not allowed_shapes_raw:
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="allowed_shapes must be a non-empty list.",
        )
    allowed_shapes: set[tuple[int, ...]] = set()
    for entry in allowed_shapes_raw:
        if not isinstance(entry, list) or not entry:
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason="allowed_shapes entries must be non-empty integer lists.",
            )
        if any((not isinstance(i, int)) for i in entry):
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason="allowed_shapes entries must contain integers only.",
            )
        shape = tuple(sorted(set(entry)))
        if any(i not in allowed_set for i in shape):
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason="allowed_shapes contains levels outside allowed_levels.",
            )
        allowed_shapes.add(shape)
    if not allowed_shapes:
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="allowed_shapes resolved to empty set.",
        )

    shape_status_raw = raw.get("shape_status")
    if not isinstance(shape_status_raw, list) or not shape_status_raw:
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="shape_status must be a non-empty list.",
        )
    shape_status_map: dict[tuple[int, ...], str] = {}
    for entry in shape_status_raw:
        if not isinstance(entry, dict):
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason="shape_status entries must be objects.",
            )
        levels = entry.get("levels")
        status = entry.get("status")
        if not isinstance(levels, list) or not levels:
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason="shape_status.levels must be a non-empty list.",
            )
        if any((not isinstance(i, int)) for i in levels):
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason="shape_status.levels entries must be integers.",
            )
        if status not in {"ok", "partial", "failed"}:
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason="shape_status.status must be one of ok/partial/failed.",
            )
        shape = tuple(sorted(set(levels)))
        if shape not in allowed_shapes:
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason="shape_status references shape not in allowed_shapes.",
            )
        shape_status_map[shape] = status
    if not shape_status_map:
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="shape_status map resolved to empty.",
        )

    layers_raw = raw.get("layers")
    if not isinstance(layers_raw, dict):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="layers must be an object.",
        )
    hierarchy_required = layers_raw.get("hierarchy_required")
    repair_required = layers_raw.get("repair_required")
    if not isinstance(hierarchy_required, bool):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="layers.hierarchy_required must be boolean.",
        )
    if not isinstance(repair_required, bool):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="layers.repair_required must be boolean.",
        )

    hierarchy_raw = raw.get("hierarchy_repair_rules")
    if not isinstance(hierarchy_raw, dict):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="hierarchy_repair_rules must be an object.",
        )
    hierarchy_parent_level = hierarchy_raw.get("parent_level")
    hierarchy_child_levels = hierarchy_raw.get("child_levels")
    if not isinstance(hierarchy_parent_level, int):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="hierarchy_repair_rules.parent_level must be integer.",
        )
    hierarchy_child_set = set(
        _as_int_list(
            hierarchy_child_levels,
            field="hierarchy_repair_rules.child_levels",
            dataset_dir=root,
            allow_empty=not hierarchy_required,
        )
    )

    repair_raw = raw.get("repair_rules")
    if not isinstance(repair_raw, dict):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="repair_rules must be an object.",
        )
    repair_parent_level = repair_raw.get("parent_level")
    repair_child_levels = repair_raw.get("child_levels")
    if not isinstance(repair_parent_level, int):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="repair_rules.parent_level must be integer.",
        )
    repair_child_set = set(
        _as_int_list(
            repair_child_levels,
            field="repair_rules.child_levels",
            dataset_dir=root,
            allow_empty=not repair_required,
        )
    )

    if hierarchy_parent_level not in allowed_set:
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="hierarchy_repair_rules.parent_level must be in allowed_levels.",
        )
    if repair_parent_level not in allowed_set:
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="repair_rules.parent_level must be in allowed_levels.",
        )
    if any(c not in allowed_set for c in hierarchy_child_set):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="hierarchy_repair_rules.child_levels must be in allowed_levels.",
        )
    if any(c not in allowed_set for c in repair_child_set):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="repair_rules.child_levels must be in allowed_levels.",
        )

    nearby_raw = raw.get("nearby_policy", {})
    if nearby_raw is None:
        nearby_raw = {}
    if not isinstance(nearby_raw, dict):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="nearby_policy must be an object when present.",
        )

    nearby_fallback_enabled = nearby_raw.get("enabled", True)
    if not isinstance(nearby_fallback_enabled, bool):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="nearby_policy.enabled must be boolean.",
        )

    nearby_max_distance_km = nearby_raw.get("max_distance_km", 2.0)
    if nearby_max_distance_km is not None:
        if not isinstance(nearby_max_distance_km, (int, float)):
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason="nearby_policy.max_distance_km must be number or null.",
            )
        if float(nearby_max_distance_km) <= 0:
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason="nearby_policy.max_distance_km must be > 0 when present.",
            )
        nearby_max_distance_km = float(nearby_max_distance_km)

    offshore_max_distance_km = nearby_raw.get("offshore_max_distance_km", 20.0)
    if offshore_max_distance_km is not None:
        if not isinstance(offshore_max_distance_km, (int, float)):
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason="nearby_policy.offshore_max_distance_km must be number or null.",
            )
        if float(offshore_max_distance_km) <= 0:
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason="nearby_policy.offshore_max_distance_km must be > 0 when present.",
            )
        offshore_max_distance_km = float(offshore_max_distance_km)

    if (
        nearby_max_distance_km is not None
        and offshore_max_distance_km is not None
        and nearby_max_distance_km > offshore_max_distance_km
    ):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="nearby_policy.max_distance_km must be <= nearby_policy.offshore_max_distance_km.",
        )

    optional_layers_raw = raw.get("optional_layers", [])
    if optional_layers_raw is None:
        optional_layers_raw = []
    if not isinstance(optional_layers_raw, list):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(root),
            reason="optional_layers must be a list when present.",
        )
    optional_layers: list[OptionalLayerDeclaration] = []
    seen_names: set[str] = set()
    for idx, entry in enumerate(optional_layers_raw):
        if not isinstance(entry, dict):
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason=f"optional_layers[{idx}] must be an object.",
            )
        name = entry.get("name")
        file_name = entry.get("file")
        layer_type = entry.get("type")
        stage = entry.get("stage")
        deterministic = entry.get("deterministic")
        if not isinstance(name, str) or not name.strip():
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason=f"optional_layers[{idx}].name is required.",
            )
        if name in seen_names:
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason=f"optional_layers has duplicate name: {name!r}.",
            )
        seen_names.add(name)
        if not isinstance(file_name, str) or not file_name.strip():
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason=f"optional_layers[{idx}].file is required.",
            )
        rel = Path(file_name.strip())
        if rel.is_absolute() or ".." in rel.parts:
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason=f"optional_layers[{idx}].file must be a relative path within dataset root.",
            )
        if layer_type != "semantic_overlay":
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason=f"optional_layers[{idx}].type must be 'semantic_overlay'.",
            )
        if stage != "post_status":
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason=f"optional_layers[{idx}].stage must be 'post_status'.",
            )
        if deterministic is not True:
            raise RuntimePolicyInvalidError(
                dataset_dir=str(root),
                reason=f"optional_layers[{idx}].deterministic must be true.",
            )
        optional_layers.append(
            OptionalLayerDeclaration(
                name=name.strip(),
                file=rel.as_posix(),
                type=layer_type,
                stage=stage,
                deterministic=True,
            )
        )

    return RuntimePolicy(
        runtime_policy_version=version.strip(),
        allowed_levels=sorted(allowed_set),
        allowed_shapes=allowed_shapes,
        shape_status_map=shape_status_map,
        hierarchy_parent_level=hierarchy_parent_level,
        hierarchy_child_levels=hierarchy_child_set,
        repair_parent_level=repair_parent_level,
        repair_child_levels=repair_child_set,
        hierarchy_required=hierarchy_required,
        repair_required=repair_required,
        nearby_fallback_enabled=nearby_fallback_enabled,
        nearby_max_distance_km=nearby_max_distance_km,
        offshore_max_distance_km=offshore_max_distance_km,
        optional_layers=tuple(optional_layers),
    )


def load_geometry_index(dataset_dir: str | Path) -> FFSFSpatialIndexV3:
    root = Path(dataset_dir)
    return FFSFSpatialIndexV3.from_files(
        ffsf_path=root / "geometry.ffsf",
        feature_meta_path=root / "geometry_meta.json",
    )


def load_hierarchy_parent_map(
    dataset_dir: str | Path,
    *,
    child_levels: set[int],
    parent_level: int,
) -> dict[str, dict[str, Any]]:
    root = Path(dataset_dir)
    raw = json.loads((root / "hierarchy.json").read_text(encoding="utf-8"))
    nodes = raw.get("nodes", [])
    node_by_id = {n["id"]: n for n in nodes if isinstance(n, dict) and n.get("id")}
    by_child_name: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("level") not in child_levels:
            continue
        parent = node_by_id.get(node.get("parent_id"))
        if not parent or parent.get("level") != parent_level:
            continue
        child_name = node.get("name")
        if not isinstance(child_name, str) or not child_name:
            continue
        by_child_name[child_name] = {
            "level": parent_level,
            "name": parent.get("name"),
            "osm_id": parent.get("id"),
            "source": "admin_tree_name",
        }
    return by_child_name


def load_repair_anchor_map(dataset_dir: str | Path) -> tuple[dict[str, tuple[str, str]], str]:
    root = Path(dataset_dir)
    raw = json.loads((root / "repair.json").read_text(encoding="utf-8"))
    anchors = raw.get("l8_to_l4_anchor", {})
    canonical = raw.get("canonical_l4", {})
    normalized: dict[str, tuple[str, str]] = {}
    for l8_name, mapping in anchors.items():
        if not isinstance(l8_name, str) or not l8_name:
            continue
        if isinstance(mapping, str):
            l4_id = mapping
            l4_name = canonical.get(mapping)
        elif isinstance(mapping, dict):
            l4_id = mapping.get("l4_semantic_id")
            l4_name = mapping.get("l4_name")
        else:
            continue
        if not isinstance(l4_id, str) or not l4_id:
            continue
        if not isinstance(l4_name, str) or not l4_name:
            l4_name = canonical.get(l4_id)
        if not isinstance(l4_name, str) or not l4_name:
            continue
        normalized[l8_name] = (l4_name, l4_id)
    return normalized, "loaded_external"


def load_dataset_country_name(dataset_dir: str | Path) -> str:
    root = Path(dataset_dir)
    manifest_path = root / "dataset_release_manifest.json"
    if not manifest_path.exists():
        return "Unknown Country"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return "Unknown Country"
    country_name = raw.get("country_name")
    if isinstance(country_name, str) and country_name.strip():
        return country_name.strip()
    country_iso = raw.get("country_iso")
    if isinstance(country_iso, str) and country_iso.strip():
        return country_iso.strip().upper()
    dataset_id = raw.get("dataset_id")
    if isinstance(dataset_id, str) and dataset_id.strip():
        return dataset_id.strip()
    return "Unknown Country"


@dataclass(frozen=True)
class SemanticOverlay:
    name: str
    file: str
    result_metadata: dict[str, Any]
    name_overrides_by_osm_id: dict[str, str]

    def apply(self, public_bundle: dict[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(public_bundle)
        result = out.setdefault("result", {})
        if self.result_metadata:
            overlays = result.setdefault("semantic_overlays", {})
            overlays[self.name] = copy.deepcopy(self.result_metadata)
        if self.name_overrides_by_osm_id:
            hierarchy = result.get("admin_hierarchy", [])
            if isinstance(hierarchy, list):
                for node in hierarchy:
                    if not isinstance(node, dict):
                        continue
                    osm_id = node.get("osm_id")
                    if isinstance(osm_id, str) and osm_id in self.name_overrides_by_osm_id:
                        node["name"] = self.name_overrides_by_osm_id[osm_id]
        return out


def _load_overlay_file(path: Path, *, dataset_dir: Path, overlay_name: str) -> SemanticOverlay:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimePolicyInvalidError(
            dataset_dir=str(dataset_dir),
            reason=f"optional overlay {overlay_name!r} is malformed JSON: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(dataset_dir),
            reason=f"optional overlay {overlay_name!r} must be a JSON object.",
        )
    allowed_keys = {"overlay_version", "result_metadata", "name_overrides_by_osm_id"}
    unknown = sorted(set(raw.keys()) - allowed_keys)
    if unknown:
        raise RuntimePolicyInvalidError(
            dataset_dir=str(dataset_dir),
            reason=f"optional overlay {overlay_name!r} contains unsupported keys: {unknown}",
        )
    result_metadata = raw.get("result_metadata", {})
    if not isinstance(result_metadata, dict):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(dataset_dir),
            reason=f"optional overlay {overlay_name!r} result_metadata must be an object.",
        )
    name_overrides = raw.get("name_overrides_by_osm_id", {})
    if not isinstance(name_overrides, dict):
        raise RuntimePolicyInvalidError(
            dataset_dir=str(dataset_dir),
            reason=f"optional overlay {overlay_name!r} name_overrides_by_osm_id must be an object.",
        )
    for k, v in name_overrides.items():
        if not isinstance(k, str) or not k:
            raise RuntimePolicyInvalidError(
                dataset_dir=str(dataset_dir),
                reason=f"optional overlay {overlay_name!r} override keys must be non-empty strings.",
            )
        if not isinstance(v, str) or not v:
            raise RuntimePolicyInvalidError(
                dataset_dir=str(dataset_dir),
                reason=f"optional overlay {overlay_name!r} override values must be non-empty strings.",
            )
    if not result_metadata and not name_overrides:
        raise RuntimePolicyInvalidError(
            dataset_dir=str(dataset_dir),
            reason=f"optional overlay {overlay_name!r} must define at least one deterministic transform.",
        )
    return SemanticOverlay(
        name=overlay_name,
        file=path.name,
        result_metadata=result_metadata,
        name_overrides_by_osm_id=name_overrides,
    )


def ensure_declared_overlay_files_present(dataset_dir: str | Path, policy: RuntimePolicy) -> None:
    root = Path(dataset_dir)
    missing = [decl.file for decl in policy.optional_layers if not (root / decl.file).exists()]
    if missing:
        raise DatasetNotBootstrappedError(str(root), sorted(missing))


def load_semantic_overlays(dataset_dir: str | Path, policy: RuntimePolicy) -> list[SemanticOverlay]:
    root = Path(dataset_dir)
    overlays: list[SemanticOverlay] = []
    for decl in policy.optional_layers:
        overlays.append(_load_overlay_file(root / decl.file, dataset_dir=root, overlay_name=decl.name))
    return overlays


def apply_semantic_overlays(public_bundle: dict[str, Any], overlays: list[SemanticOverlay]) -> dict[str, Any]:
    if not overlays:
        return public_bundle
    status_before = public_bundle.get("lookup_status")
    hierarchy_before = [
        node
        for node in public_bundle.get("result", {}).get("admin_hierarchy", [])
        if isinstance(node, dict)
    ]
    node_count_before = len(hierarchy_before)
    osm_ids_before = [node.get("osm_id") for node in hierarchy_before]
    levels_before = [node.get("level") for node in hierarchy_before]
    ranks_before = [node.get("rank", "__MISSING__") for node in hierarchy_before]

    out = copy.deepcopy(public_bundle)
    for overlay in overlays:
        out = overlay.apply(out)

    status_after = out.get("lookup_status")
    hierarchy_after = [
        node
        for node in out.get("result", {}).get("admin_hierarchy", [])
        if isinstance(node, dict)
    ]
    node_count_after = len(hierarchy_after)
    osm_ids_after = [node.get("osm_id") for node in hierarchy_after]
    levels_after = [node.get("level") for node in hierarchy_after]
    ranks_after = [node.get("rank", "__MISSING__") for node in hierarchy_after]
    if status_after != status_before:
        raise RuntimeError("semantic overlay must not modify lookup_status.")
    if node_count_after != node_count_before:
        raise RuntimeError("semantic overlay must not change hierarchy node count.")
    if osm_ids_after != osm_ids_before:
        raise RuntimeError("semantic overlay must not modify/reorder osm_id sequence.")
    if levels_after != levels_before:
        raise RuntimeError("semantic overlay must not modify structural hierarchy levels.")
    if ranks_after != ranks_before:
        raise RuntimeError("semantic overlay must not modify/reorder rank sequence.")
    return out
