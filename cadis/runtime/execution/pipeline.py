from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from cadis.runtime.core_adapter import AdminEngineCore
from cadis.runtime.dataset.loader import (
    RuntimePolicy,
    apply_semantic_overlays,
    ensure_declared_overlay_files_present,
    load_dataset_country_name,
    load_geometry_index,
    load_hierarchy_parent_map,
    load_repair_anchor_map,
    load_runtime_policy,
    load_semantic_overlays,
)
from cadis.runtime.errors import DatasetNotBootstrappedError
from cadis.version import __version__


def evaluate_lookup_status(
    nodes: list[dict],
    *,
    allowed_shapes: set[tuple[int, ...]],
    shape_status_map: dict[tuple[int, ...], str],
) -> str:
    if not nodes:
        return "failed"
    levels = tuple(sorted({int(n["level"]) for n in nodes if n.get("level") is not None}))
    if levels not in allowed_shapes:
        return "failed"
    return shape_status_map.get(levels, "partial")


class CadisLookupPipeline:
    """Dataset-driven lookup interpreter with no country-engine imports."""

    def __init__(self, *, dataset_dir: str | Path, country_name: str | None = None):
        self.dataset_dir = Path(dataset_dir)
        self._assert_bootstrapped_base_dataset()
        self.policy: RuntimePolicy = load_runtime_policy(self.dataset_dir)
        self._assert_required_policy_layers()
        self.semantic_overlays = load_semantic_overlays(self.dataset_dir, self.policy)
        self.country_name = (
            country_name.strip()
            if isinstance(country_name, str) and country_name.strip()
            else load_dataset_country_name(self.dataset_dir)
        )
        self.allowed_levels = list(self.policy.allowed_levels)
        self.allowed_shapes = set(self.policy.allowed_shapes)
        self.core = AdminEngineCore(enable_v2_shadow=False)
        self.geometry_index = load_geometry_index(self.dataset_dir)
        if self.policy.hierarchy_required:
            self.hierarchy_parent_map = load_hierarchy_parent_map(
                self.dataset_dir,
                child_levels=set(self.policy.hierarchy_child_levels),
                parent_level=self.policy.hierarchy_parent_level,
            )
        else:
            self.hierarchy_parent_map = {}
        if self.policy.repair_required:
            self.repair_anchor_map, self.repair_loader_reason_code = load_repair_anchor_map(self.dataset_dir)
        else:
            self.repair_anchor_map, self.repair_loader_reason_code = {}, "disabled_by_policy"

    def _assert_bootstrapped_base_dataset(self) -> None:
        required = [
            "dataset_release_manifest.json",
            "geometry.ffsf",
            "geometry_meta.json",
            "runtime_policy.json",
        ]
        missing = [name for name in required if not (self.dataset_dir / name).exists()]
        if missing:
            raise DatasetNotBootstrappedError(str(self.dataset_dir), missing)

    def _assert_required_policy_layers(self) -> None:
        required: list[str] = []
        if self.policy.hierarchy_required:
            required.append("hierarchy.json")
        if self.policy.repair_required:
            required.append("repair.json")
        required.extend([decl.file for decl in self.policy.optional_layers])
        missing = [name for name in required if not (self.dataset_dir / name).exists()]
        if missing:
            raise DatasetNotBootstrappedError(str(self.dataset_dir), missing)
        ensure_declared_overlay_files_present(self.dataset_dir, self.policy)

    def _hierarchy_provider(self, evidence: dict[int, dict], missing_levels: set[int]) -> dict[int, dict]:
        if not self.policy.hierarchy_required:
            return {}
        parent_level = self.policy.hierarchy_parent_level
        if parent_level not in missing_levels:
            return {}
        for child_level in sorted(self.policy.hierarchy_child_levels):
            child = evidence.get(child_level, {})
            name = child.get("name")
            if not isinstance(name, str) or not name:
                continue
            node = self.hierarchy_parent_map.get(name)
            if node:
                return {parent_level: node}
        return {}

    def _repair_provider(self, evidence: dict[int, dict], missing_levels: set[int]) -> dict[int, dict]:
        if not self.policy.repair_required:
            return {}
        parent_level = self.policy.repair_parent_level
        if parent_level not in missing_levels:
            return {}
        for child_level in sorted(self.policy.repair_child_levels):
            child = evidence.get(child_level, {})
            name = child.get("name")
            if not isinstance(name, str) or not name:
                continue
            mapped = self.repair_anchor_map.get(name)
            if not mapped:
                continue
            return {
                parent_level: {
                    "level": parent_level,
                    "name": mapped[0],
                    "osm_id": mapped[1],
                    "source": "semantic_anchor",
                }
            }
        return {}

    def _build_offshore_result(self) -> dict[str, Any]:
        return {
            "lookup_status": "ok",
            "engine": "cadis",
            "version": __version__,
            "state": {
                "dataset": {"status": "ready"},
                "boundary": {
                    "classification": "offshore",
                    "label": self.country_name,
                },
            },
            "result": {
                "country": {
                    "level": 2,
                    "name": self.country_name,
                },
                "admin_hierarchy": [],
                "source": "offshore",
            },
        }

    @staticmethod
    def _attach_ready_dataset_state(bundle: dict[str, Any]) -> dict[str, Any]:
        out = dict(bundle)
        state = out.setdefault("state", {})
        if not isinstance(state, dict):
            out["state"] = {"dataset": {"status": "ready"}}
            return out
        dataset_state = state.setdefault("dataset", {})
        if not isinstance(dataset_state, dict):
            state["dataset"] = {"status": "ready"}
            return out
        dataset_state.setdefault("status", "ready")
        return out

    def _nearby_enabled(self) -> bool:
        return (
            self.policy.nearby_fallback_enabled
            and self.policy.nearby_max_distance_km is not None
            and self.policy.offshore_max_distance_km is not None
            and self.geometry_index.has_country_scope_geometry()
        )

    def lookup(self, lat: float, lon: float) -> dict[str, Any]:
        pt = SimpleNamespace(x=float(lon), y=float(lat))
        polygon_hits = self.geometry_index.query_point(pt, self.allowed_levels)

        if not polygon_hits and self._nearby_enabled():
            is_inside_country_scope = self.geometry_index.country_scope_contains_point(pt)
            if not is_inside_country_scope:
                distance_km = self.geometry_index.distance_km_to_country_scope(pt)
                nearby_km = float(self.policy.nearby_max_distance_km)
                offshore_km = float(self.policy.offshore_max_distance_km)

                if distance_km <= nearby_km:
                    polygon_hits = self.geometry_index.query_point_nearest(
                        pt,
                        nearby_km,
                        self.allowed_levels,
                    )
                elif distance_km <= offshore_km:
                    return self._attach_ready_dataset_state(
                        apply_semantic_overlays(
                            self._build_offshore_result(),
                            self.semantic_overlays,
                        )
                    )

        bundle = self.core.run_v2_shadow_pipeline(
            polygon_hits=polygon_hits,
            allowed_levels=self.allowed_levels,
            allowed_shapes=self.allowed_shapes,
            engine="cadis",
            version=__version__,
            country_name=self.country_name,
            hierarchy_provider=self._hierarchy_provider,
            repair_provider=self._repair_provider,
            status_evaluator=lambda nodes: evaluate_lookup_status(
                nodes,
                allowed_shapes=self.allowed_shapes,
                shape_status_map=self.policy.shape_status_map,
            ),
        )
        return self._attach_ready_dataset_state(
            apply_semantic_overlays(bundle["public"], self.semantic_overlays)
        )


RuntimeLookupPipeline = CadisLookupPipeline
