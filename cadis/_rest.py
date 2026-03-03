"""Minimal REST server for remote Cadis integration."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from ._api import SUPPORTED_ISO2, bootstrap, info, lookup, reinstall

_PRIVATE_KEYS = {
    "dataset_dir",
    "dataset_manifest_url",
    "release_manifest_url",
    "package_url",
    "package_sha_url",
    "downloaded_urls",
    "cache_dir",
}


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _sanitize_payload(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if key in _PRIVATE_KEYS:
                continue
            out[key] = _sanitize_payload(value)
        return out
    if isinstance(obj, list):
        return [_sanitize_payload(v) for v in obj]
    return obj


def _public_bootstrap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    minimal: dict[str, Any] = {}
    for key in ("engine", "version", "bootstrap_status", "state"):
        if key in payload:
            minimal[key] = payload[key]
    dataset = payload.get("dataset")
    if isinstance(dataset, dict):
        summary: dict[str, Any] = {}
        for key in ("country_iso2", "dataset_id", "dataset_version"):
            if key in dataset:
                summary[key] = dataset[key]
        if summary:
            minimal["dataset"] = summary
    return _sanitize_payload(minimal)


def _extract_iso2_from_lookup(payload: dict[str, Any]) -> str | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    world = state.get("world")
    if isinstance(world, dict):
        iso2 = world.get("iso2")
        if isinstance(iso2, str) and len(iso2.strip()) == 2:
            return iso2.strip().upper()
    dataset = state.get("dataset")
    if isinstance(dataset, dict):
        iso2 = dataset.get("iso2")
        if isinstance(iso2, str) and len(iso2.strip()) == 2:
            return iso2.strip().upper()
    return None


def _dataset_status(payload: dict[str, Any]) -> str | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    dataset = state.get("dataset")
    if not isinstance(dataset, dict):
        return None
    status = dataset.get("status")
    if isinstance(status, str):
        return status
    return None


def _world_classification(payload: dict[str, Any]) -> str | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    world = state.get("world")
    if not isinstance(world, dict):
        return None
    classification = world.get("classification")
    if isinstance(classification, str):
        return classification
    return None


def _apply_lazy_lookup(lat: float, lon: float, *, auto_update: bool) -> dict[str, Any]:
    first = lookup(lat, lon)
    if not isinstance(first, dict):
        return first

    iso2 = _extract_iso2_from_lookup(first)
    if iso2 is None or iso2 not in SUPPORTED_ISO2:
        return first

    classification = _world_classification(first)
    if classification != "country":
        return first

    first_status = str(first.get("execution", {}).get("lookup_status", "failed"))
    ds_status = _dataset_status(first)
    if not auto_update and not (first_status == "failed" and ds_status in {"missing", "invalid"}):
        return first

    remediation = bootstrap(iso2, update_to_latest=True)
    if remediation.get("bootstrap_status") != "ready":
        return first

    second = lookup(lat, lon)
    if isinstance(second, dict):
        return second
    return first


def perform_lookup(
    lat: float,
    lon: float,
    *,
    mode: str = "lazy",
    auto_update: bool = True,
) -> dict[str, Any]:
    if mode == "strict":
        return lookup(lat, lon)
    return _apply_lazy_lookup(lat, lon, auto_update=auto_update)


class _CadisRestHandler(BaseHTTPRequestHandler):
    server_version = "cadis-rest/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            _json_response(self, HTTPStatus.OK, {"status": "ok"})
            return
        if parsed.path == "/info":
            _json_response(self, HTTPStatus.OK, info())
            return
        _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw_body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return
        if not isinstance(body, dict):
            _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid_payload"})
            return

        if parsed.path == "/lookup":
            mode = str(body.get("mode", "lazy")).strip().lower()
            if mode not in {"lazy", "strict"}:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid_mode"})
                return
            auto_update = body.get("auto_update", True)
            auto_update = bool(auto_update)
            try:
                lat = float(body["lat"])
                lon = float(body["lon"])
            except Exception:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid_coordinates"})
                return
            payload = perform_lookup(lat, lon, mode=mode, auto_update=auto_update)
            _json_response(self, HTTPStatus.OK, _sanitize_payload(payload))
            return

        if parsed.path == "/bootstrap":
            iso2 = body.get("iso2")
            if not isinstance(iso2, str):
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid_iso2"})
                return
            force_reinstall = bool(body.get("force_reinstall", False))
            update_to_latest = bool(body.get("update_to_latest", False))
            payload = bootstrap(
                iso2,
                force_reinstall=force_reinstall,
                update_to_latest=update_to_latest,
            )
            _json_response(self, HTTPStatus.OK, _public_bootstrap_payload(payload))
            return

        if parsed.path == "/reinstall":
            iso2 = body.get("iso2")
            if not isinstance(iso2, str):
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "invalid_iso2"})
                return
            update_to_latest = bool(body.get("update_to_latest", False))
            payload = reinstall(iso2, update_to_latest=update_to_latest)
            _json_response(self, HTTPStatus.OK, _public_bootstrap_payload(payload))
            return

        _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cadisd")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), _CadisRestHandler)
    print(f"Cadis REST server listening on {args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
