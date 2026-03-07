"""Dataset serving policy for Cadis control-layer contexts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable


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

    return normalize_allowed_iso2(raw.split(","))


def normalize_allowed_iso2(values: Iterable[str] | None) -> frozenset[str]:
    if values is None:
        return frozenset()

    allowed: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            continue
        normalized = item.strip().upper()
        if len(normalized) == 2 and normalized.isalpha():
            allowed.add(normalized)
    return frozenset(allowed)


def load_dataset_policy_from_env() -> DatasetPolicy:
    allowed_iso2 = _parse_allowed_iso2(os.environ.get("CADIS_ALLOWED_ISO2"))
    return DatasetPolicy(enabled=bool(allowed_iso2), allowed_iso2=allowed_iso2)


def make_dataset_policy(allowed_iso2: Iterable[str] | None = None) -> DatasetPolicy:
    normalized = normalize_allowed_iso2(allowed_iso2)
    return DatasetPolicy(enabled=bool(normalized), allowed_iso2=normalized)
