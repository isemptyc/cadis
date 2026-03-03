from __future__ import annotations

from typing import Any, Literal, TypedDict

LookupStatus = Literal["ok", "partial", "failed"]
DatasetStatus = Literal["ready", "missing", "invalid"]


class CountryInfo(TypedDict):
    level: int
    name: str


class AdminHierarchyNode(TypedDict):
    rank: int
    osm_id: str | None
    level: int
    name: str
    source: str


class LookupResult(TypedDict, total=False):
    country: CountryInfo
    admin_hierarchy: list[AdminHierarchyNode]
    source: str
    context_anchor: dict[str, Any]
    semantic_overlays: dict[str, Any]


class DatasetState(TypedDict, total=False):
    status: DatasetStatus
    detail_code: str
    details: dict[str, Any]


class BoundaryState(TypedDict, total=False):
    classification: str
    label: str


class RuntimeState(TypedDict, total=False):
    dataset: DatasetState
    boundary: BoundaryState


class LookupResponse(TypedDict):
    lookup_status: LookupStatus
    engine: str
    version: str
    result: LookupResult
    state: RuntimeState


class DatasetInspection(TypedDict):
    dataset_dir: str
    state: RuntimeState


class BootstrapResult(TypedDict):
    bootstrap_status: Literal["ready", "failed"]
    dataset_dir: str
    state: RuntimeState
