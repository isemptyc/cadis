"""Dataset serving policy for Cadis process-level control."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetPolicy:
    enabled: bool = False
    allowed_iso2: frozenset[str] = frozenset()

    def allows(self, iso2: str) -> bool:
        normalized = iso2.strip().upper()
        if not self.enabled:
            return True
        return normalized in self.allowed_iso2


def _parse_allowed_iso2(raw: str | None) -> frozenset[str]:
    if not isinstance(raw, str):
        return frozenset()

    allowed: set[str] = set()
    for item in raw.split(","):
        normalized = item.strip().upper()
        if len(normalized) == 2 and normalized.isalpha():
            allowed.add(normalized)
    return frozenset(allowed)


def load_dataset_policy_from_env() -> DatasetPolicy:
    allowed_iso2 = _parse_allowed_iso2(os.environ.get("CADIS_ALLOWED_ISO2"))
    return DatasetPolicy(enabled=bool(allowed_iso2), allowed_iso2=allowed_iso2)
