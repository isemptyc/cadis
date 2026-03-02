"""Command-line interface for cadis."""

from __future__ import annotations

import argparse
import json
from typing import Any, Sequence

from . import info as api_info
from . import lookup as api_lookup


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cadis")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lookup_parser = subparsers.add_parser("lookup")
    lookup_parser.add_argument("lat", type=float)
    lookup_parser.add_argument("lon", type=float)
    lookup_parser.add_argument("--json", action="store_true", dest="as_json")

    subparsers.add_parser("info")
    return parser


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_lookup_human(payload: dict[str, Any]) -> int:
    status = payload.get("lookup_status")
    reason = payload.get("reason")

    if status == "failed":
        message = reason if isinstance(reason, str) and reason else "unknown_error"
        print(f"Lookup failed: {message}")
        return 1

    if status == "partial":
        message = reason if isinstance(reason, str) and reason else "partial_result"
        print(f"Lookup partial: {message}")
        return 0

    print("Lookup succeeded")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "info":
        _print_json(api_info())
        return 0

    payload = api_lookup(args.lat, args.lon)

    if args.as_json:
        _print_json(payload)
        return 0

    if isinstance(payload, dict):
        return _print_lookup_human(payload)

    print("Lookup failed: internal_error")
    return 1
