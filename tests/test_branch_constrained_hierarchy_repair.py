from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from cadis.runtime.dataset.loader import (
    HierarchyBranchIndex,
    HierarchyBranchNode,
    load_hierarchy_branch_index,
)
from cadis.runtime.execution import pipeline as pipeline_mod
from cadis.runtime.execution.pipeline import CadisLookupPipeline


def _pipeline(index: HierarchyBranchIndex) -> CadisLookupPipeline:
    pipeline = CadisLookupPipeline.__new__(CadisLookupPipeline)
    pipeline.policy = SimpleNamespace(
        hierarchy_required=True,
        hierarchy_parent_level=6,
        hierarchy_child_levels={7, 8},
    )
    pipeline.hierarchy_branch_index = index
    return pipeline


def _geometry_index(*metas: dict) -> SimpleNamespace:
    return SimpleNamespace(
        feature_meta_by_index=list(metas),
        feature_id_to_index={
            meta["feature_id"]: idx
            for idx, meta in enumerate(metas)
            if isinstance(meta.get("feature_id"), str)
        },
    )


def _lazy_pipeline(tmp_path: Path, *, hierarchy_required: bool, repair_required: bool) -> CadisLookupPipeline:
    pipeline = CadisLookupPipeline.__new__(CadisLookupPipeline)
    pipeline.dataset_dir = tmp_path
    pipeline.policy = SimpleNamespace(
        hierarchy_required=hierarchy_required,
        hierarchy_parent_level=6,
        hierarchy_child_levels={7, 8},
        repair_required=repair_required,
        repair_parent_level=6,
        repair_child_levels={7, 8},
    )
    pipeline._hierarchy_branch_index_cache = pipeline_mod._UNSET if hierarchy_required else None
    pipeline._repair_anchor_map_cache = pipeline_mod._UNSET if repair_required else {}
    pipeline._repair_loader_reason_code = "not_loaded" if repair_required else "disabled_by_policy"
    return pipeline


def _index(nodes: list[HierarchyBranchNode]) -> HierarchyBranchIndex:
    node_by_id = {node.id: node for node in nodes}
    id_aliases = {}
    name_counts = {}
    first_id_by_name = {}
    for node in nodes:
        id_aliases[node.id] = node.id
        id_aliases[f"pt_{node.id}"] = node.id
        name_counts[node.name] = name_counts.get(node.name, 0) + 1
        first_id_by_name.setdefault(node.name, node.id)
    unique_id_by_name = {
        name: node_id
        for name, node_id in first_id_by_name.items()
        if name_counts[name] == 1
    }
    return HierarchyBranchIndex(
        node_by_id=node_by_id,
        id_aliases=id_aliases,
        unique_id_by_name=unique_id_by_name,
    )


def _branch_node(
    node_id: str,
    level: int,
    name: str,
    parent_id: str | None,
    path_ids: tuple[str, ...],
    *,
    branch_id: str,
) -> HierarchyBranchNode:
    path_signature = hashlib.sha256("\x1f".join(path_ids).encode("utf-8")).hexdigest()
    return HierarchyBranchNode(
        node_id,
        level,
        name,
        parent_id,
        None,
        root_id=path_ids[0],
        branch_id=branch_id,
        path_ids=path_ids,
        path_signature=path_signature,
    )


def _explicit_index(nodes: list[HierarchyBranchNode]) -> HierarchyBranchIndex:
    base = _index(nodes)
    return HierarchyBranchIndex(
        node_by_id=base.node_by_id,
        id_aliases=base.id_aliases,
        unique_id_by_name=base.unique_id_by_name,
        branch_identity_version="1.0",
        explicit_branch_identity=True,
    )


def _write_hierarchy_dataset(root: Path, nodes: list[dict], *, version: str | None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset_release_manifest.json").write_text(
        json.dumps({"country_iso": "PT"}),
        encoding="utf-8",
    )
    payload = {"nodes": nodes}
    if version is not None:
        payload["branch_identity_version"] = version
    (root / "hierarchy.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_repair_uses_parent_from_polygon_branch_path():
    index = _index(
        [
            HierarchyBranchNode("r6", 6, "Faro", None, None),
            HierarchyBranchNode("r7", 7, "Lagoa", "r6", None),
            HierarchyBranchNode("r8", 8, "Lagoa e Carvoeiro", "r7", None),
        ]
    )

    result = _pipeline(index)._hierarchy_provider(
        {8: {"osm_id": "pt_r8", "name": "Lagoa e Carvoeiro"}},
        {6, 7},
    )

    assert result == {
        6: {
            "level": 6,
            "name": "Faro",
            "osm_id": "r6",
            "source": "admin_tree_id",
        }
    }


def test_hierarchy_parent_public_node_is_enriched_from_prefixed_geometry_alias():
    index = _index(
        [
            HierarchyBranchNode("r6", 6, "Faro", None, None),
            HierarchyBranchNode("r8", 8, "Lagoa e Carvoeiro", "r6", None),
        ]
    )
    pipeline = _pipeline(index)
    pipeline.geometry_index = _geometry_index(
        {
            "feature_id": "pt_r6",
            "level": 6,
            "name": "Faro",
            "names": {"en": "Faro", "pt": "Faro"},
        }
    )

    result = pipeline._hierarchy_provider(
        {8: {"osm_id": "pt_r8", "name": "Lagoa e Carvoeiro"}},
        {6},
    )

    assert result == {
        6: {
            "level": 6,
            "name": "Faro",
            "osm_id": "pt_r6",
            "source": "admin_tree_id",
            "names": {"en": "Faro", "pt": "Faro"},
        }
    }


def test_hierarchy_index_loads_lazily_until_parent_level_is_missing(tmp_path, monkeypatch):
    calls = 0
    index = _index(
        [
            HierarchyBranchNode("r6", 6, "Faro", None, None),
            HierarchyBranchNode("r7", 7, "Lagoa", "r6", None),
        ]
    )

    def load_index(dataset_dir):
        nonlocal calls
        calls += 1
        return index

    monkeypatch.setattr(pipeline_mod, "load_hierarchy_branch_index", load_index)
    pipeline = _lazy_pipeline(tmp_path, hierarchy_required=True, repair_required=False)

    assert pipeline._hierarchy_provider({7: {"osm_id": "pt_r7", "name": "Lagoa"}}, {8}) == {}
    assert calls == 0

    assert pipeline._hierarchy_provider({7: {"osm_id": "pt_r7", "name": "Lagoa"}}, {6}) == {
        6: {
            "level": 6,
            "name": "Faro",
            "osm_id": "r6",
            "source": "admin_tree_id",
        }
    }
    assert calls == 1


def test_repair_public_node_is_enriched_from_prefixed_geometry_suffix(tmp_path, monkeypatch):
    def load_repair(dataset_dir):
        return {"Child": ("Faro", "r6")}, "loaded"

    monkeypatch.setattr(pipeline_mod, "load_repair_anchor_map", load_repair)
    pipeline = _lazy_pipeline(tmp_path, hierarchy_required=False, repair_required=True)
    pipeline.geometry_index = _geometry_index(
        {
            "feature_id": "pt_r6",
            "level": 6,
            "name": "Faro",
            "names": {"en": "Faro", "pt": "Faro"},
        }
    )

    assert pipeline._repair_provider({7: {"name": "Child"}}, {6}) == {
        6: {
            "level": 6,
            "name": "Faro",
            "osm_id": "pt_r6",
            "source": "semantic_anchor",
            "names": {"en": "Faro", "pt": "Faro"},
        }
    }


def test_repair_map_loads_lazily_until_parent_level_is_missing(tmp_path, monkeypatch):
    calls = 0

    def load_repair(dataset_dir):
        nonlocal calls
        calls += 1
        return {"Child": ("Parent", "parent_id")}, "loaded"

    monkeypatch.setattr(pipeline_mod, "load_repair_anchor_map", load_repair)
    pipeline = _lazy_pipeline(tmp_path, hierarchy_required=False, repair_required=True)

    assert pipeline._repair_provider({7: {"name": "Child"}}, {8}) == {}
    assert calls == 0

    assert pipeline._repair_provider({7: {"name": "Child"}}, {6}) == {
        6: {
            "level": 6,
            "name": "Parent",
            "osm_id": "parent_id",
            "source": "semantic_anchor",
        }
    }
    assert calls == 1


def test_loader_enables_explicit_branch_identity_only_when_valid(tmp_path):
    root = tmp_path / "valid"
    root_path = ("root",)
    child_path = ("root", "child")
    _write_hierarchy_dataset(
        root,
        [
            {
                "id": "root",
                "level": 4,
                "name": "Portugal",
                "parent_id": None,
                "root_id": "root",
                "branch_id": "root",
                "path_ids": list(root_path),
                "path_signature": hashlib.sha256(
                    "\x1f".join(root_path).encode("utf-8")
                ).hexdigest(),
            },
            {
                "id": "child",
                "level": 6,
                "name": "Faro",
                "parent_id": "root",
                "root_id": "root",
                "branch_id": "root",
                "path_ids": list(child_path),
                "path_signature": hashlib.sha256(
                    "\x1f".join(child_path).encode("utf-8")
                ).hexdigest(),
            },
        ],
        version="1.0",
    )

    index = load_hierarchy_branch_index(root)

    assert index.explicit_branch_identity is True
    assert [node.id for node in index.path_to_root("pt_child")] == ["child", "root"]


def test_loader_falls_back_when_explicit_branch_identity_is_invalid(tmp_path):
    root = tmp_path / "invalid"
    _write_hierarchy_dataset(
        root,
        [
            {
                "id": "root",
                "level": 4,
                "name": "Portugal",
                "parent_id": None,
                "root_id": "root",
                "branch_id": "root",
                "path_ids": ["root"],
                "path_signature": "invalid",
            },
            {
                "id": "child",
                "level": 6,
                "name": "Faro",
                "parent_id": "root",
                "root_id": "root",
                "branch_id": "root",
                "path_ids": ["root", "child"],
                "path_signature": "invalid",
            },
        ],
        version="1.0",
    )

    index = load_hierarchy_branch_index(root)

    assert index.explicit_branch_identity is False
    assert [node.id for node in index.path_to_root("pt_child")] == ["child", "root"]


def test_repair_does_not_cross_branch_for_duplicate_child_name():
    index = _index(
        [
            HierarchyBranchNode("r4", 4, "Acores", None, None),
            HierarchyBranchNode("r6", 6, "Faro", None, None),
            HierarchyBranchNode("r7_island", 7, "Lagoa", "r4", None),
            HierarchyBranchNode("r8_island", 8, "Agua de Pau", "r7_island", None),
            HierarchyBranchNode("r7_mainland", 7, "Lagoa", "r6", None),
            HierarchyBranchNode("r8_mainland", 8, "Lagoa e Carvoeiro", "r7_mainland", None),
        ]
    )

    result = _pipeline(index)._hierarchy_provider(
        {
            4: {"osm_id": "pt_r4", "name": "Acores"},
            7: {"osm_id": "pt_r7_island", "name": "Lagoa"},
            8: {"osm_id": "pt_r8_island", "name": "Agua de Pau"},
        },
        {6},
    )

    assert result == {}


def test_repair_candidate_must_be_compatible_with_existing_ancestor():
    index = _index(
        [
            HierarchyBranchNode("r4_a", 4, "Acores", None, None),
            HierarchyBranchNode("r4_b", 4, "Mainland", None, None),
            HierarchyBranchNode("r6_b", 6, "Faro", "r4_b", None),
            HierarchyBranchNode("r7_b", 7, "Lagoa", "r6_b", None),
            HierarchyBranchNode("r8_b", 8, "Lagoa e Carvoeiro", "r7_b", None),
        ]
    )

    result = _pipeline(index)._hierarchy_provider(
        {
            4: {"osm_id": "pt_r4_a", "name": "Acores"},
            8: {"osm_id": "pt_r8_b", "name": "Lagoa e Carvoeiro"},
        },
        {6, 7},
    )

    assert result == {}


def test_unique_name_fallback_only_runs_without_branch_evidence():
    index = _index(
        [
            HierarchyBranchNode("r6", 6, "Faro", None, None),
            HierarchyBranchNode("r7", 7, "Unique Child", "r6", None),
        ]
    )

    result = _pipeline(index)._hierarchy_provider(
        {7: {"name": "Unique Child"}},
        {6},
    )

    assert result == {
        6: {
            "level": 6,
            "name": "Faro",
            "osm_id": "r6",
            "source": "admin_tree_unique_name",
        }
    }


def test_explicit_branch_identity_rejects_branch_mismatch():
    index = _explicit_index(
        [
            _branch_node(
                "root_a",
                4,
                "Acores",
                None,
                ("root_a",),
                branch_id="branch_a",
            ),
            _branch_node(
                "root_b",
                4,
                "Mainland",
                None,
                ("root_b",),
                branch_id="branch_b",
            ),
            _branch_node(
                "r6_b",
                6,
                "Faro",
                "root_b",
                ("root_b", "r6_b"),
                branch_id="branch_b",
            ),
            _branch_node(
                "r8_b",
                8,
                "Lagoa e Carvoeiro",
                "r6_b",
                ("root_b", "r6_b", "r8_b"),
                branch_id="branch_b",
            ),
        ]
    )

    result = _pipeline(index)._hierarchy_provider(
        {
            4: {"osm_id": "pt_root_a", "name": "Acores"},
            8: {"osm_id": "pt_r8_b", "name": "Lagoa e Carvoeiro"},
        },
        {6},
    )

    assert result == {}


def test_explicit_branch_identity_uses_path_membership():
    index = _explicit_index(
        [
            _branch_node("root", 4, "Portugal", None, ("root",), branch_id="root"),
            _branch_node("r6", 6, "Faro", "root", ("root", "r6"), branch_id="root"),
            _branch_node(
                "r8",
                8,
                "Lagoa e Carvoeiro",
                "r6",
                ("root", "r6", "r8"),
                branch_id="root",
            ),
        ]
    )

    result = _pipeline(index)._hierarchy_provider(
        {8: {"osm_id": "pt_r8", "name": "Lagoa e Carvoeiro"}},
        {6},
    )

    assert result == {
        6: {
            "level": 6,
            "name": "Faro",
            "osm_id": "r6",
            "source": "admin_tree_id",
        }
    }
