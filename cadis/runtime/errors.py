from __future__ import annotations


class DatasetNotBootstrappedError(RuntimeError):
    """Raised when runtime lookup is attempted before dataset bootstrap."""

    def __init__(self, dataset_dir: str, missing_files: list[str]):
        self.dataset_dir = dataset_dir
        self.missing_files = missing_files
        super().__init__(
            f"Dataset is not bootstrapped: dir={dataset_dir} missing={missing_files}"
        )


class RuntimePolicyInvalidError(RuntimeError):
    """Raised when runtime_policy.json is missing or invalid."""

    def __init__(self, *, dataset_dir: str, reason: str):
        self.dataset_dir = dataset_dir
        self.reason = reason
        super().__init__(f"Runtime policy invalid: dir={dataset_dir} reason={reason}")
