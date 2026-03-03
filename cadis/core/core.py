import copy
import logging
import os
from typing import Any, Callable


class AdminEngineCore:
    """
    Responsibility:
        AdminEngineCore contains ONLY structural, country-agnostic logic
        that is shared identically across all admin lookup engines
        (Japan, UK, Taiwan, and future countries).

    What This Code MUST NOT Do:
        - MUST NOT perform hierarchy traversal
        - MUST NOT infer or repair parent relationships
        - MUST NOT classify or interpret orphan nodes
        - MUST NOT evaluate semantic success or failure
        - MUST NOT apply country-specific rules
        - MUST NOT modify behavior based on country

    Why This Code Lives Here:
        This logic exists identically in all country engines and produces
        the same intermediate results regardless of country context.
        Placing it here prevents accidental semantic drift and enforces
        a strict separation between structural processing (Core)
        and semantic judgment (Country Engines).
    """

    LOADER_REASON_LOADED_EXTERNAL = "loaded_external"
    LOADER_REASON_FALLBACK_BUNDLED = "fallback_bundled"
    LOADER_REASON_FALLBACK_HARDCODED = "fallback_hardcoded"
    LOADER_REASON_REJECTED_MISSING_FIELDS = "rejected_missing_fields"
    LOADER_REASON_REJECTED_MALFORMED_JSON = "rejected_malformed_json"
    LOADER_REASON_REJECTED_COUNTRY_MISMATCH = "rejected_country_mismatch"
    _LOADER_REASON_CODES = {
        LOADER_REASON_LOADED_EXTERNAL,
        LOADER_REASON_FALLBACK_BUNDLED,
        LOADER_REASON_FALLBACK_HARDCODED,
        LOADER_REASON_REJECTED_MISSING_FIELDS,
        LOADER_REASON_REJECTED_MALFORMED_JSON,
        LOADER_REASON_REJECTED_COUNTRY_MISMATCH,
    }

    def __init__(
        self,
        *,
        enable_v2_shadow: bool | None = None,
        telemetry_hook: Callable[[str, dict], None] | None = None,
    ):
        self._logger = logging.getLogger(__name__)
        self._telemetry_hook = telemetry_hook
        self._v2_shadow_enabled = (
            os.getenv("CADIS_CORE_V2_SHADOW") == "1"
            if enable_v2_shadow is None
            else bool(enable_v2_shadow)
        )
        self._telemetry_enabled = os.getenv("CADIS_CORE_V2_TELEMETRY") == "1"

    def is_shadow_mode_enabled(self) -> bool:
        return self._v2_shadow_enabled

    def _emit_telemetry(self, stage: str, payload: dict) -> None:
        if self._telemetry_hook is not None:
            self._telemetry_hook(stage, payload)
            return
        if self._telemetry_enabled:
            self._logger.info("[CoreV2][%s] %s", stage, payload)

    def report_loader_reason_code(self, code: str, *, details: str = "") -> None:
        if code not in self._LOADER_REASON_CODES:
            return
        payload = {"code": code}
        if details:
            payload["details"] = details
        self._emit_telemetry("loader_reason_code", payload)

    def collect_nodes(self, raw_records):
        """
        Responsibility:
            Collect raw administrative nodes from lookup input
            without interpreting their meaning.

        What This Code MUST NOT Do:
            - MUST NOT filter by admin_level
            - MUST NOT infer hierarchy or parent relationships
            - MUST NOT remove or normalize nodes
            - MUST NOT sort nodes
            - MUST NOT evaluate semantic validity

        Why This Code Lives Here:
            Node collection is a purely mechanical operation shared by
            all country engines. It precedes any country-specific
            interpretation and therefore belongs to AdminEngineCore.
        """
        if raw_records is None:
            return []
        if isinstance(raw_records, dict):
            return list(raw_records.values())
        return list(raw_records)

    def filter_allowed_levels(self, nodes, allowed_levels):
        """
        Responsibility:
            Remove administrative nodes whose admin_level is not allowed
            by the active country policy.

        What This Code MUST NOT Do:
            - MUST NOT reorder nodes
            - MUST NOT deduplicate nodes
            - MUST NOT promote or demote admin levels
            - MUST NOT apply country-specific heuristics

        Why This Code Lives Here:
            The act of filtering by a provided level set is structurally
            identical across countries. The decision of WHICH levels are
            allowed belongs to country engines, but the filtering mechanism
            itself is shared and therefore belongs to AdminEngineCore.
        """
        allowed = set(allowed_levels)
        return [node for node in nodes if node.get("level") in allowed]

    def sort_by_level(self, nodes):
        """
        Responsibility:
            Sort administrative nodes by admin_level in ascending order
            while preserving original relative order for equal levels.

        What This Code MUST NOT Do:
            - MUST NOT re-level nodes semantically
            - MUST NOT apply country-specific ordering rules
            - MUST NOT collapse or expand hierarchy

        Why This Code Lives Here:
            Level-based ordering is a structural normalization step required
            by all engines before semantic evaluation. It is independent of
            country meaning and therefore belongs to AdminEngineCore.

        Note:
            This implementation relies on Python's stable sort guarantee
            to preserve original relative order for equal levels.
        """
        return sorted(nodes, key=lambda n: n.get("level"))

    def deduplicate(self, nodes):
        """
        Responsibility:
            Remove exact duplicate administrative nodes according to
            existing engine behavior.

        What This Code MUST NOT Do:
            - MUST NOT perform fuzzy matching
            - MUST NOT normalize names or identifiers
            - MUST NOT apply country-specific deduplication rules

        Why This Code Lives Here:
            Deduplication logic is mechanically identical across all
            country engines and operates purely on node identity,
            not on semantic meaning.
        """
        seen = set()
        unique = []
        for node in nodes:
            key = (
                node.get("level"),
                node.get("osm_id"),
                node.get("name"),
                node.get("source"),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(node)
        return unique

    def collect_geometry_evidence(self, polygon_hits: dict[int, dict] | None) -> dict[int, dict]:
        """
        Stage v2.1: collect geometry evidence with explicit evidence tagging.
        """
        raw = polygon_hits or {}
        geometry: dict[int, dict] = {}
        for level in sorted(raw.keys()):
            node = copy.deepcopy(raw[level])
            node["level"] = int(node.get("level", level))
            node.setdefault("source", "polygon")
            node["evidence_type"] = "geometry"
            geometry[level] = node
        self._emit_telemetry(
            "collect_geometry_evidence",
            {
                "levels": sorted(geometry.keys()),
                "count": len(geometry),
            },
        )
        return geometry

    @staticmethod
    def _normalize_supplement_nodes(
        *,
        supplement_nodes: dict[int, dict] | None,
        source_default: str,
        evidence_type_default: str,
        allowed_levels: list[int],
        existing_levels: set[int],
    ) -> dict[int, dict]:
        out: dict[int, dict] = {}
        if not supplement_nodes:
            return out

        allowed = set(allowed_levels)
        for level in sorted(supplement_nodes.keys()):
            if level in existing_levels or level not in allowed:
                continue
            node = copy.deepcopy(supplement_nodes[level])
            node["level"] = int(node.get("level", level))
            node.setdefault("source", source_default)
            node["evidence_type"] = evidence_type_default
            out[level] = node
        return out

    def supplement_from_hierarchy(
        self,
        geometry_evidence: dict[int, dict],
        *,
        allowed_levels: list[int],
        hierarchy_provider: Callable[[dict[int, dict], set[int]], dict[int, dict]] | None = None,
    ) -> dict[int, dict]:
        """
        Stage v2.2: hierarchy supplementation.
        """
        missing_levels = set(allowed_levels) - set(geometry_evidence.keys())
        raw = {}
        if hierarchy_provider is not None and missing_levels:
            raw = hierarchy_provider(geometry_evidence, missing_levels) or {}

        supplemented = self._normalize_supplement_nodes(
            supplement_nodes=raw,
            source_default="admin_tree_name",
            evidence_type_default="hierarchy_repair",
            allowed_levels=allowed_levels,
            existing_levels=set(geometry_evidence.keys()),
        )
        self._emit_telemetry(
            "supplement_from_hierarchy",
            {
                "missing_levels": sorted(missing_levels),
                "added_levels": sorted(supplemented.keys()),
                "count": len(supplemented),
            },
        )
        return supplemented

    def supplement_from_repair_dataset(
        self,
        merged_evidence: dict[int, dict],
        *,
        allowed_levels: list[int],
        repair_provider: Callable[[dict[int, dict], set[int]], dict[int, dict]] | None = None,
    ) -> dict[int, dict]:
        """
        Stage v2.3: dataset-governed repair supplementation.
        """
        missing_levels = set(allowed_levels) - set(merged_evidence.keys())
        raw = {}
        if repair_provider is not None and missing_levels:
            raw = repair_provider(merged_evidence, missing_levels) or {}

        supplemented = self._normalize_supplement_nodes(
            supplement_nodes=raw,
            source_default="semantic_anchor",
            evidence_type_default="semantic_anchor",
            allowed_levels=allowed_levels,
            existing_levels=set(merged_evidence.keys()),
        )
        self._emit_telemetry(
            "supplement_from_repair_dataset",
            {
                "missing_levels": sorted(missing_levels),
                "added_levels": sorted(supplemented.keys()),
                "count": len(supplemented),
            },
        )
        return supplemented

    def validate_allowed_shapes(
        self,
        nodes: list[dict],
        *,
        allowed_shapes: set[tuple[int, ...]],
        shape_status_map: dict[tuple[int, ...], str] | None = None,
    ) -> tuple[str, tuple[int, ...]]:
        """
        Stage v2.4: policy shape validation.
        """
        shape = tuple(sorted({int(n["level"]) for n in nodes if n.get("level") is not None}))
        if shape not in allowed_shapes:
            status = "failed"
        elif shape_status_map and shape in shape_status_map:
            status = shape_status_map[shape]
        else:
            status = "partial"

        self._emit_telemetry(
            "validate_allowed_shapes",
            {
                "shape": shape,
                "status": status,
            },
        )
        return status, shape

    @staticmethod
    def _merge_evidence_in_priority_order(*layers: dict[int, dict]) -> dict[int, dict]:
        merged: dict[int, dict] = {}
        for layer in layers:
            for level in sorted(layer.keys()):
                if level not in merged:
                    merged[level] = copy.deepcopy(layer[level])
        return merged

    @staticmethod
    def _assign_rank(nodes: list[dict]) -> list[dict]:
        ranked: list[dict] = []
        for i, node in enumerate(nodes):
            out = copy.deepcopy(node)
            out["rank"] = i
            ranked.append(out)
        return ranked

    def assemble_result(
        self,
        *,
        nodes: list[dict],
        status: str,
        engine: str,
        version: str,
        country_name: str,
        result_source: str | None = None,
        context_anchor: dict | None = None,
    ) -> dict:
        """
        Stage v2.5: stable result assembly (public envelope).
        """
        ranked_nodes = self._assign_rank(self.sort_by_level(nodes))
        self._emit_telemetry(
            "assemble_result",
            {
                "status": status,
                "count": len(ranked_nodes),
            },
        )
        return self.build_base_result(
            ranked_nodes,
            status,
            engine,
            version,
            country_name,
            result_source=result_source,
            context_anchor=context_anchor,
        )

    def run_v2_shadow_pipeline(
        self,
        *,
        polygon_hits: dict[int, dict],
        allowed_levels: list[int],
        allowed_shapes: set[tuple[int, ...]],
        engine: str,
        version: str,
        country_name: str,
        hierarchy_provider: Callable[[dict[int, dict], set[int]], dict[int, dict]] | None = None,
        repair_provider: Callable[[dict[int, dict], set[int]], dict[int, dict]] | None = None,
        status_evaluator: Callable[[list[dict]], str] | None = None,
        shape_status_map: dict[tuple[int, ...], str] | None = None,
        result_source: str | None = None,
        context_anchor: dict | None = None,
    ) -> dict[str, Any]:
        """
        Phase-A shadow execution path. Does not decide production authority.
        """
        geometry = self.collect_geometry_evidence(polygon_hits)

        hierarchy_supplement = self.supplement_from_hierarchy(
            geometry,
            allowed_levels=allowed_levels,
            hierarchy_provider=hierarchy_provider,
        )
        merged_after_hierarchy = self._merge_evidence_in_priority_order(geometry, hierarchy_supplement)

        repair_supplement = self.supplement_from_repair_dataset(
            merged_after_hierarchy,
            allowed_levels=allowed_levels,
            repair_provider=repair_provider,
        )
        merged = self._merge_evidence_in_priority_order(
            geometry,
            hierarchy_supplement,
            repair_supplement,
        )

        nodes = self.collect_nodes(merged)
        nodes = self.filter_allowed_levels(nodes, allowed_levels)
        nodes = self.sort_by_level(nodes)
        nodes = self.deduplicate(nodes)

        status, shape = self.validate_allowed_shapes(
            nodes,
            allowed_shapes=allowed_shapes,
            shape_status_map=shape_status_map,
        )
        if status_evaluator is not None:
            status = status_evaluator(nodes)
            self._emit_telemetry(
                "validate_allowed_shapes_override",
                {"shape": shape, "status": status},
            )

        final_nodes = nodes if status != "failed" else []
        public_result = self.assemble_result(
            nodes=final_nodes,
            status=status,
            engine=engine,
            version=version,
            country_name=country_name,
            result_source=result_source,
            context_anchor=context_anchor,
        )
        internal_result = {
            "nodes": self._assign_rank(final_nodes),
            "status": status,
            "engine": engine,
            "version": version,
            "country": country_name,
        }
        return {
            "internal": internal_result,
            "public": public_result,
            "stages": {
                "geometry": geometry,
                "hierarchy": hierarchy_supplement,
                "repair": repair_supplement,
                "shape": shape,
            },
        }

    def build_base_result(
        self,
        nodes,
        status,
        engine,
        version,
        country_name,
        result_source: str | None = None,
        context_anchor: dict | None = None,
    ):
        """
        Responsibility:
            Construct the final lookup result object from a list of nodes
            and an externally computed semantic status.

        What This Code MUST NOT Do:
            - MUST NOT compute or alter semantic status
            - MUST NOT validate structural completeness
            - MUST NOT modify the node list

        Why This Code Lives Here:
            Result assembly is a shared, mechanical operation.
            Semantic meaning is injected by country engines, not Core.
        """
        result = {
            "lookup_status": status,
            "engine": engine,
            "version": version,
            "result": {
                "country": {
                    "level": 2,
                    "name": country_name,
                },
                "admin_hierarchy": [
                    {
                        "rank": node["rank"],
                        "osm_id": node.get("osm_id"),
                        "level": node["level"],
                        "name": node["name"],
                        "source": node.get("source", "polygon"),
                    }
                    for node in nodes
                ],
            },
        }
        if result_source:
            result["result"]["source"] = result_source
        if context_anchor:
            result["result"]["context_anchor"] = context_anchor
        return result
