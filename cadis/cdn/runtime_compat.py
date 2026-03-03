from __future__ import annotations

from typing import Any


def parse_semver(raw: str, *, field: str) -> tuple[int, ...]:
    value = raw.strip()
    if value.startswith("v"):
        value = value[1:]
    parts = value.split(".")
    if not parts or any(not p.isdigit() for p in parts):
        raise ValueError(f"Manifest invalid {field} (expected semver-like digits, e.g. 2.0.0).")
    return tuple(int(p) for p in parts)


def validate_manifest_runtime_compatibility(
    manifest: dict[str, Any],
    *,
    runtime_version: str,
) -> tuple[str, str]:
    runtime_compat = manifest.get("runtime_compat")
    if not isinstance(runtime_compat, dict):
        raise ValueError("Manifest missing runtime_compat object.")

    min_cadis_version = runtime_compat.get("min")
    if not isinstance(min_cadis_version, str) or not min_cadis_version.strip():
        raise ValueError("Manifest missing runtime_compat.min.")

    max_cadis_version_exclusive = runtime_compat.get("max_exclusive")
    if not isinstance(max_cadis_version_exclusive, str) or not max_cadis_version_exclusive.strip():
        raise ValueError("Manifest missing runtime_compat.max_exclusive.")

    runtime_v = parse_semver(runtime_version, field="cadis runtime version")
    min_v = parse_semver(min_cadis_version, field="min_cadis_version")
    max_v = parse_semver(max_cadis_version_exclusive, field="max_cadis_version_exclusive")

    if min_v >= max_v:
        raise ValueError(
            "Manifest has invalid runtime range: min_cadis_version must be < max_cadis_version_exclusive."
        )
    if runtime_v < min_v:
        raise ValueError(
            f"Cadis runtime {runtime_version} is lower than required min_cadis_version {min_cadis_version}."
        )
    if runtime_v >= max_v:
        raise ValueError(
            f"Cadis runtime {runtime_version} is not supported (>= max_cadis_version_exclusive {max_cadis_version_exclusive})."
        )

    return min_cadis_version.strip(), max_cadis_version_exclusive.strip()
