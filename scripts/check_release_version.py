#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
MODULE_VERSION_PATH = ROOT / "cadis" / "version.py"
VERSION_PATTERN = re.compile(r'^version = "([^"]+)"$', re.MULTILINE)
MODULE_VERSION_PATTERN = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)


def _read_project_version(pyproject_path: Path) -> str:
    match = VERSION_PATTERN.search(pyproject_path.read_text())
    if match is None:
        raise ValueError(f"Could not find project version in {pyproject_path}.")
    return match.group(1)


def _read_module_version(module_version_path: Path) -> str:
    match = MODULE_VERSION_PATTERN.search(module_version_path.read_text())
    if match is None:
        raise ValueError(f"Could not find __version__ in {module_version_path}.")
    return match.group(1)


def normalize_tag(tag: str) -> str:
    normalized = tag.strip()
    if normalized.startswith("refs/tags/"):
        normalized = normalized[len("refs/tags/") :]
    if normalized.startswith("v"):
        normalized = normalized[1:]
    if not normalized:
        raise ValueError("Release tag must not be empty.")
    return normalized


def validate_release_version(tag: str) -> str:
    tag_version = normalize_tag(tag)
    project_version = _read_project_version(PYPROJECT_PATH)
    module_version = _read_module_version(MODULE_VERSION_PATH)

    if project_version != module_version:
        raise ValueError(
            "Version mismatch between pyproject.toml "
            f"({project_version}) and cadis/version.py ({module_version})."
        )

    if tag_version != project_version:
        raise ValueError(
            f"Git tag version ({tag_version}) does not match package version ({project_version})."
        )

    return tag_version


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"Usage: {argv[0]} TAG", file=sys.stderr)
        return 1

    version = validate_release_version(argv[1])
    print(f"release version verified: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
