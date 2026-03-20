from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cadis._api import SUPPORTED_ISO2
from cadis.cdn.bootstrap import DEFAULT_DATASET_MANIFEST_URL
from cadis.version import __version__


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_dataset_manifest(*, url: str, timeout_sec: int) -> dict[str, Any]:
    with urlopen(url, timeout=timeout_sec) as response:
        return json.loads(response.read().decode("utf-8"))


def build_stable_manifest(
    *,
    dataset_manifest: dict[str, Any],
    dataset_manifest_url: str,
    cadis_version: str,
    updated_at: str,
) -> dict[str, Any]:
    countries = dataset_manifest.get("countries")
    if not isinstance(countries, dict):
        raise ValueError("dataset_manifest.json missing countries object.")

    source_generated_at = dataset_manifest.get("generated_at")
    if not isinstance(source_generated_at, str) or not source_generated_at.strip():
        raise ValueError("dataset_manifest.json missing generated_at.")

    datasets: dict[str, str] = {}
    for iso2 in SUPPORTED_ISO2:
        country_block = countries.get(iso2)
        if not isinstance(country_block, dict):
            raise ValueError(f"dataset_manifest.json missing country {iso2}.")
        dataset_id = f"{iso2.lower()}.admin"
        dataset_entry = country_block.get(dataset_id)
        if not isinstance(dataset_entry, dict):
            raise ValueError(f"dataset_manifest.json missing dataset entry {dataset_id} for {iso2}.")
        latest = dataset_entry.get("latest")
        if not isinstance(latest, str) or not latest.strip():
            raise ValueError(f"dataset_manifest.json missing latest version for {iso2}.")
        datasets[iso2] = latest.strip()

    return {
        "profile": "cadis.deployment.release",
        "schema_version": 1,
        "release_name": "stable",
        "release_channel": "production",
        "source_dataset_manifest_url": dataset_manifest_url,
        "source_dataset_manifest_generated_at": source_generated_at.strip(),
        "updated_at": updated_at,
        "cadis_version": cadis_version,
        "datasets": datasets,
    }


def write_stable_manifest(*, manifest_path: Path, payload: dict[str, Any]) -> None:
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refresh releases/stable.json from the upstream Cadis dataset manifest."
    )
    parser.add_argument(
        "--manifest-path",
        default="releases/stable.json",
        help="Path to the stable release manifest to update.",
    )
    parser.add_argument(
        "--dataset-manifest-url",
        default=DEFAULT_DATASET_MANIFEST_URL,
        help="Upstream dataset_manifest.json URL.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=30,
        help="Network timeout for fetching the upstream dataset manifest.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero instead of rewriting when the stable manifest is stale.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest_path = Path(args.manifest_path)
    dataset_manifest = fetch_dataset_manifest(
        url=args.dataset_manifest_url,
        timeout_sec=args.timeout_sec,
    )
    current_payload = None
    if manifest_path.exists():
        current_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    updated_at = (
        str(current_payload.get("updated_at")).strip()
        if isinstance(current_payload, dict)
        and isinstance(current_payload.get("updated_at"), str)
        and current_payload.get("updated_at").strip()
        else _utc_now_iso()
    )
    expected = build_stable_manifest(
        dataset_manifest=dataset_manifest,
        dataset_manifest_url=args.dataset_manifest_url,
        cadis_version=__version__,
        updated_at=updated_at,
    )

    if args.check:
        if current_payload == expected:
            print("stable release manifest is current")
            return 0
        print(json.dumps(expected, indent=2, sort_keys=False))
        return 1

    expected["updated_at"] = _utc_now_iso()
    write_stable_manifest(manifest_path=manifest_path, payload=expected)
    print(json.dumps(expected, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
