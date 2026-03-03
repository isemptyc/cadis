from __future__ import annotations

from pathlib import Path
from typing import Any

from cadis.runtime.errors import DatasetNotBootstrappedError, RuntimePolicyInvalidError
from cadis.runtime.execution.pipeline import CadisLookupPipeline
from cadis.runtime.types import BootstrapResult, DatasetInspection, RuntimeState


def _dataset_state_missing(detail_code: str, details: dict[str, Any]) -> RuntimeState:
    return {
        "dataset": {
            "status": "missing",
            "detail_code": detail_code,
            "details": details,
        }
    }


def _dataset_state_invalid(detail_code: str, details: dict[str, Any]) -> RuntimeState:
    return {
        "dataset": {
            "status": "invalid",
            "detail_code": detail_code,
            "details": details,
        }
    }


def inspect_dataset(dataset_dir: str | Path) -> DatasetInspection:
    root = Path(dataset_dir).expanduser()

    if not root.exists():
        return {
            "dataset_dir": str(root),
            "state": _dataset_state_missing(
                "dataset_dir_not_found",
                {"dataset_dir": str(root)},
            ),
        }
    if not root.is_dir():
        return {
            "dataset_dir": str(root),
            "state": _dataset_state_invalid(
                "dataset_dir_not_directory",
                {"dataset_dir": str(root)},
            ),
        }

    try:
        pipeline = CadisLookupPipeline(dataset_dir=root)
    except DatasetNotBootstrappedError as exc:
        return {
            "dataset_dir": str(root),
            "state": _dataset_state_missing(
                "required_files_missing",
                {
                    "dataset_dir": exc.dataset_dir,
                    "missing_files": sorted(exc.missing_files),
                },
            ),
        }
    except RuntimePolicyInvalidError as exc:
        return {
            "dataset_dir": str(root),
            "state": _dataset_state_invalid(
                "runtime_policy_invalid",
                {
                    "dataset_dir": exc.dataset_dir,
                    "reason": exc.reason,
                },
            ),
        }
    except Exception as exc:  # pragma: no cover - unexpected loader failure boundary
        return {
            "dataset_dir": str(root),
            "state": _dataset_state_invalid(
                "dataset_load_failed",
                {
                    "dataset_dir": str(root),
                    "exception": str(exc),
                    "exception_type": exc.__class__.__name__,
                },
            ),
        }

    return {
        "dataset_dir": str(root),
        "state": {
            "dataset": {
                "status": "ready",
                "detail_code": "dataset_ready",
                "details": {
                    "runtime_policy_version": pipeline.policy.runtime_policy_version,
                    "allowed_levels": pipeline.allowed_levels,
                },
            }
        },
    }


def bootstrap_dataset(dataset_dir: str | Path) -> BootstrapResult:
    inspection = inspect_dataset(dataset_dir)
    dataset_state = inspection["state"]["dataset"]
    if dataset_state.get("status") == "ready":
        return {
            "bootstrap_status": "ready",
            "dataset_dir": inspection["dataset_dir"],
            "state": inspection["state"],
        }
    return {
        "bootstrap_status": "failed",
        "dataset_dir": inspection["dataset_dir"],
        "state": inspection["state"],
    }
