"""Command-line interface for cadis."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Callable, Sequence

from . import bootstrap as api_bootstrap
from . import info as api_info
from . import lookup as api_lookup
from . import reinstall as api_reinstall
from ._cache import resolve_cache_dir
from ._country_names import COUNTRY_NAMES


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cadis")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lookup_parser = subparsers.add_parser("lookup")
    lookup_parser.add_argument("lat", type=float)
    lookup_parser.add_argument("lon", type=float)
    lookup_parser.add_argument("--json", action="store_true", dest="as_json")

    info_parser = subparsers.add_parser("info")
    info_parser.add_argument("--json", action="store_true", dest="as_json")

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--iso2")
    prepare_parser.add_argument("--dataset-version")
    prepare_parser.add_argument("--output-dir")
    return parser


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _format_iso2_line(iso2: str) -> str:
    upper = iso2.upper()
    name = _country_label(upper)
    return f"- {upper} ({name})"


def _print_info_human(payload: dict[str, Any]) -> None:
    version = payload.get("version")
    supported = payload.get("supported_iso2")
    installed = payload.get("installed_iso2")
    lockdown_enabled = bool(payload.get("dataset_lockdown_enabled"))
    allowed = payload.get("allowed_iso2")

    print(f"Cadis {version}" if isinstance(version, str) else "Cadis")
    print("")
    print("Supported:")
    if isinstance(supported, list) and supported:
        for iso2 in supported:
            if isinstance(iso2, str) and iso2.strip():
                print(_format_iso2_line(iso2))
    else:
        print("- (none)")
    print("")
    print("Installed:")
    if isinstance(installed, list) and installed:
        for iso2 in installed:
            if isinstance(iso2, str) and iso2.strip():
                print(_format_iso2_line(iso2))
    else:
        print("- (none)")
    print("")
    print("Dataset Lockdown:")
    print("- enabled" if lockdown_enabled else "- disabled")
    if lockdown_enabled:
        print("")
        print("Allowed:")
        if isinstance(allowed, list) and allowed:
            for iso2 in allowed:
                if isinstance(iso2, str) and iso2.strip():
                    print(_format_iso2_line(iso2))
        else:
            print("- (none)")


def _confirm(prompt: str) -> bool:
    answer = input(prompt).strip().lower()
    return answer in {"y", "yes"}


def _render_download_progress() -> tuple[Callable[[str, int, int | None], None], Callable[[], None]]:
    state = {"last_width": 0, "active": False}
    interactive = os.isatty(1)

    def on_progress(_url: str, downloaded: int, total: int | None) -> None:
        if not interactive:
            return
        state["active"] = True
        if total and total > 0:
            pct = min(100.0, (downloaded / total) * 100.0)
            line = (
                f"Downloading dataset... {pct:5.1f}% "
                f"({downloaded / 1048576:.1f}/{total / 1048576:.1f} MB)"
            )
        else:
            line = f"Downloading dataset... {downloaded / 1048576:.1f} MB"

        pad = max(0, state["last_width"] - len(line))
        print(f"\r{line}{' ' * pad}", end="", flush=True)
        state["last_width"] = len(line)

    def finish() -> None:
        if interactive and state["active"]:
            print()

    return on_progress, finish

def _supported_iso2() -> set[str]:
    payload = api_info()
    if not isinstance(payload, dict):
        return set()
    raw = payload.get("supported_iso2")
    if not isinstance(raw, list):
        return set()
    supported: set[str] = set()
    for item in raw:
        if isinstance(item, str) and item.strip():
            supported.add(item.strip().upper())
    return supported


def _country_label(iso2: str) -> str:
    upper = iso2.strip().upper()
    return COUNTRY_NAMES.get(upper, upper)


def _dataset_iso2(payload: dict[str, Any]) -> str | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    dataset = state.get("dataset")
    if isinstance(dataset, dict):
        iso2 = dataset.get("iso2")
        if isinstance(iso2, str) and iso2.strip():
            return iso2.strip().upper()
    world = state.get("world")
    if isinstance(world, dict):
        iso2 = world.get("iso2")
        if isinstance(iso2, str) and iso2.strip():
            return iso2.strip().upper()
    return None


def _summarize_result(payload: dict[str, Any]) -> str | None:
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    country = result.get("country")
    country_name = None
    if isinstance(country, dict):
        name = country.get("name")
        if isinstance(name, str) and name.strip():
            country_name = name.strip()

    parts: list[str] = []
    if country_name:
        parts.append(country_name)

    source = result.get("source")
    if source == "offshore":
        if country_name:
            parts.append("Offshore")
        else:
            parts.append("Offshore")
        return " / ".join(parts)

    hierarchy = result.get("admin_hierarchy")
    if isinstance(hierarchy, list):
        for node in hierarchy:
            if not isinstance(node, dict):
                continue
            name = node.get("name")
            if isinstance(name, str) and name.strip():
                parts.append(name.strip())

    if not parts:
        return None
    return " / ".join(parts)


def _region_from_state(payload: dict[str, Any]) -> str:
    state = payload.get("state")
    if not isinstance(state, dict):
        return "Unknown"
    world = state.get("world")
    if isinstance(world, dict):
        classification = world.get("classification")
        world_name = world.get("name")
        if isinstance(world_name, str) and world_name.strip() and classification in {
            "open_sea",
            "ocean",
            "antarctica",
            "no_sovereign_land",
        }:
            return world_name.strip()
        if classification == "country":
            iso2 = world.get("iso2")
            if isinstance(iso2, str) and iso2.strip():
                return _country_label(iso2)
        if classification == "open_sea":
            return "Open Sea"
        if classification == "ocean":
            return "Ocean"
        if classification == "antarctica":
            return "Antarctica"
        if classification == "no_sovereign_land":
            return "No Sovereign Land"

    dataset = state.get("dataset")
    if isinstance(dataset, dict):
        iso2 = dataset.get("iso2")
        if isinstance(iso2, str) and iso2.strip():
            return _country_label(iso2)
    return "Unknown"


def _maybe_run_remediation(payload: dict[str, Any]) -> tuple[int, bool]:
    state = payload.get("state")
    if not isinstance(state, dict):
        return 1, False
    dataset = state.get("dataset")
    dataset_status = dataset.get("status") if isinstance(dataset, dict) else None
    iso2 = _dataset_iso2(payload)
    supported = _supported_iso2()

    if dataset_status in {"missing", "invalid"} and iso2 and iso2 not in supported:
        print("Administrative dataset for this region is not supported in this version.")
        return 1, False

    if dataset_status == "blocked" and iso2:
        label = _country_label(iso2)
        print(f"Administrative dataset for {label} is blocked by Cadis dataset policy.")
        return 1, False

    if dataset_status == "missing" and iso2:
        label = _country_label(iso2)
        if _confirm(
            f"Cadis can provide detailed administrative hierarchy for {label}.\n"
            "Download dataset to enable full lookup? (y/N) "
        ):
            progress, finish_progress = _render_download_progress()
            try:
                remediation = api_reinstall(iso2, download_progress=progress)
            finally:
                finish_progress()
            if remediation.get("bootstrap_status") == "ready":
                return 0, True
            print("Dataset installation failed.")
            return 1, False
        return 1, False

    if dataset_status == "invalid" and iso2:
        label = _country_label(iso2)
        if _confirm(
            f"Dataset is invalid. Do you want to reinstall dataset for {label}? (y/N) "
        ):
            progress, finish_progress = _render_download_progress()
            try:
                remediation = api_reinstall(iso2, download_progress=progress)
            finally:
                finish_progress()
            if remediation.get("bootstrap_status") == "ready":
                return 0, True
            print("Dataset reinstall failed.")
            return 1, False
        return 1, False

    return 1, False


def _offer_open_sea_download(candidates: list[Any]) -> tuple[int, bool]:
    """Offer to install the best candidate country's dataset for an open-sea point.

    Returns (exit_code, should_retry). Declining is not an error — open sea is a
    valid result — so a decline returns (0, False).
    """
    best = candidates[0] if candidates and isinstance(candidates[0], dict) else None
    if not isinstance(best, dict):
        return 0, False
    iso2 = best.get("iso2")
    if not iso2:
        return 0, False
    label = best.get("name") or _country_label(iso2)
    if _confirm(
        f"This point is in open water, but it may fall inside {label}.\n"
        f"Download {label} dataset to check for a precise location? (y/N) "
    ):
        progress, finish_progress = _render_download_progress()
        try:
            remediation = api_reinstall(iso2, download_progress=progress)
        finally:
            finish_progress()
        if remediation.get("bootstrap_status") == "ready":
            return 0, True
        print("Dataset installation failed.")
        return 1, False
    return 0, False


def _print_lookup_human(payload: dict[str, Any], *, lat: float, lon: float) -> int:
    execution = payload.get("execution")
    if isinstance(execution, dict):
        status = execution.get("lookup_status")
    else:
        status = payload.get("lookup_status")

    result = payload.get("result")
    if not isinstance(result, dict):
        result = {}
    country = result.get("country")
    if not isinstance(country, dict):
        country = {}
    country_name = country.get("name")

    if not country_name:
        country_name = _region_from_state(payload)

    waterbody = result.get("waterbody") if isinstance(result, dict) else None
    if isinstance(waterbody, dict):
        waterbody_name = waterbody.get("name")
        waterbody_names = waterbody.get("names") if isinstance(waterbody.get("names"), dict) else {}
    elif isinstance(waterbody, str):  # back-compat with the flat name shape
        waterbody_name = waterbody
        waterbody_names = {}
    else:
        waterbody_name = None
        waterbody_names = {}

    if country_name:
        print(f"Region: {country_name}")
    elif waterbody_name:
        print("Region: Ocean")
    else:
        print(f"Region: {country_name}")

    if waterbody_name:
        print(f"Water Body: {waterbody_name}")
        for lang, val in waterbody_names.items():
            if val != waterbody_name:
                print(f"        {val}({lang})")

    def _print_hierarchy(result_payload: dict[str, Any]) -> None:
        hierarchy = result_payload.get("admin_hierarchy")
        if not isinstance(hierarchy, list):
            return
        for node in hierarchy:
            if not isinstance(node, dict):
                continue
            rank = node.get("rank")
            name = node.get("name")
            names = node.get("names", {})

            primary_lang = None
            if isinstance(names, dict):
                for lang, val in names.items():
                    if val == name:
                        primary_lang = lang
                        break

            line = f"Rank {rank}: {name}"
            if primary_lang:
                line += f"({primary_lang})"
            print(line)

            if isinstance(names, dict):
                for lang, val in names.items():
                    if val == name:
                        continue
                    print(f"        {val}({lang})")

    _print_hierarchy(result)

    download_candidates = result.get("download_candidates") if isinstance(result, dict) else None
    if status in {"ok", "partial"} and isinstance(download_candidates, list) and download_candidates:
        _code, should_retry = _offer_open_sea_download(download_candidates)
        if should_retry:
            retry_payload = api_lookup(lat, lon)
            if not isinstance(retry_payload, dict):
                print("Lookup failed: internal_error")
                return 1
            retry_execution = retry_payload.get("execution")
            if isinstance(retry_execution, dict):
                retry_status = retry_execution.get("lookup_status")
            else:
                retry_status = retry_payload.get("lookup_status")

            retry_result = retry_payload.get("result")
            if not isinstance(retry_result, dict):
                retry_result = {}
            retry_country = retry_result.get("country")
            if not isinstance(retry_country, dict):
                retry_country = {}
            retry_country_name = retry_country.get("name") or _region_from_state(retry_payload)

            print(f"Region: {retry_country_name}")
            _print_hierarchy(retry_result)
            return 0 if retry_status in {"ok", "partial"} else 1

    if status == "failed":
        code, should_retry = _maybe_run_remediation(payload)
        if not should_retry:
            return code

        retry_payload = api_lookup(lat, lon)
        if not isinstance(retry_payload, dict):
            print("Lookup failed: internal_error")
            return 1

        retry_execution = retry_payload.get("execution")
        if isinstance(retry_execution, dict):
            retry_status = retry_execution.get("lookup_status")
        else:
            retry_status = retry_payload.get("lookup_status")
        
        # Recalculate summary for retry
        retry_result = retry_payload.get("result")
        if not isinstance(retry_result, dict):
            retry_result = {}
        retry_country = retry_result.get("country")
        if not isinstance(retry_country, dict):
            retry_country = {}
        retry_country_name = retry_country.get("name")
        if not retry_country_name:
            retry_country_name = _region_from_state(retry_payload)

        print(f"Region: {retry_country_name}")
        _print_hierarchy(retry_result)
        return 0 if retry_status in {"ok", "partial"} else 1

    if status == "partial":
        return 0

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "info":
        payload = api_info()
        if getattr(args, "as_json", False):
            _print_json(payload)
            return 0
        if isinstance(payload, dict):
            _print_info_human(payload)
            return 0
        _print_json(payload)
        return 0

    if args.command == "prepare":
        if not getattr(args, "iso2", None):
            print("prepare requires --iso2 <code>")
            return 1

        progress, finish_progress = _render_download_progress()
        try:
            prepared = api_bootstrap(
                iso2=args.iso2,
                cache_dir=args.output_dir,
                dataset_version=args.dataset_version,
                update_to_latest=args.dataset_version is None,
                download_progress=progress,
            )
        finally:
            finish_progress()

        if not isinstance(prepared, dict) or prepared.get("bootstrap_status") != "ready":
            detail = None
            state = prepared.get("state") if isinstance(prepared, dict) else None
            dataset_state = state.get("dataset") if isinstance(state, dict) else None
            if isinstance(dataset_state, dict):
                raw_detail = dataset_state.get("detail")
                if isinstance(raw_detail, str) and raw_detail.strip():
                    detail = raw_detail.strip()
                else:
                    raw_code = dataset_state.get("detail_code")
                    if isinstance(raw_code, str) and raw_code.strip():
                        detail = raw_code.strip()
            if detail:
                print(f"Prepare failed: {detail}")
            else:
                print("Prepare failed.")
            return 1

        dataset = prepared.get("dataset")
        dataset_dir = dataset.get("dataset_dir") if isinstance(dataset, dict) else None
        dataset_version = dataset.get("dataset_version") if isinstance(dataset, dict) else None
        iso2 = str(args.iso2).upper()
        resolved_output_dir = args.output_dir or str(resolve_cache_dir())
        print(f"Prepared dataset for {iso2} under cache root {resolved_output_dir}")
        if isinstance(dataset_dir, str) and dataset_dir.strip():
            print(f"Dataset dir: {dataset_dir}")
        if isinstance(dataset_version, str) and dataset_version.strip():
            print(f"Dataset version: {dataset_version}")
        return 0

    payload = api_lookup(args.lat, args.lon)

    if args.as_json:
        _print_json(payload)
        return 0

    if isinstance(payload, dict):
        return _print_lookup_human(payload, lat=args.lat, lon=args.lon)

    print("Lookup failed: internal_error")
    return 1
