from __future__ import annotations

from types import SimpleNamespace

from cadis.runtime.dataset.loader import HierarchyBranchIndex, HierarchyBranchNode
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
