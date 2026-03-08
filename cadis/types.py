"""Public TypedDict models for Cadis SDK responses."""

from __future__ import annotations

from typing import Literal, TypedDict

LookupStatus = Literal["ok", "partial", "failed"]
ResolutionState = Literal[
    "resolved",
    "partial",
    "remediable_capability_gap",
    "blocked_by_policy",
    "terminal_non_country",
    "invalid_input",
    "engine_failure",
    "unresolved_country",
]
CapabilityDetail = Literal[
    "supported_dataset_missing",
    "unsupported_country",
    "dataset_invalid",
    "dataset_blocked_by_policy",
    "dataset_ready_unresolved",
    "input_invalid",
    "non_country_world_classification",
]
BootstrapStatus = Literal["ready", "failed"]
StateStatus = Literal["ok", "failed", "missing", "invalid", "ready", "skipped", "blocked"]


class ExecutionOutcome(TypedDict, total=False):
    lookup_status: LookupStatus
    resolution_state: ResolutionState
    capability_detail: CapabilityDetail


class InputState(TypedDict):
    status: Literal["invalid"]


class WorldState(TypedDict, total=False):
    status: StateStatus
    classification: str
    iso2: str
    name: str


class DatasetState(TypedDict, total=False):
    status: StateStatus
    iso2: str
    dataset_dir: str
    detail_code: str
    detail: str
    details: dict[str, object]


class LookupState(TypedDict, total=False):
    input: InputState
    world: WorldState
    dataset: DatasetState


class LookupResponse(TypedDict, total=False):
    engine: str
    version: str
    execution: ExecutionOutcome
    state: LookupState
    result: dict[str, object] | None


class BootstrapResponse(TypedDict, total=False):
    engine: str
    version: str
    bootstrap_status: BootstrapStatus
    state: LookupState
    dataset: dict[str, object]


class InfoResponse(TypedDict):
    schema_version: str
    version: str
    supported_iso2: list[str]
    installed_iso2: list[str]
    dataset_lockdown_enabled: bool
    allowed_iso2: list[str]
