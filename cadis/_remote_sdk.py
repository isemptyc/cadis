"""Remote SDK for Cadis REST deployment."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin
import urllib.request


class CadisRemoteSDK:
    """Programmatic client for Cadis REST server."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_sec: int = 30,
        mode: str = "lazy",
        auto_update: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout_sec = timeout_sec
        self._mode = mode
        self._auto_update = auto_update

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            urljoin(self._base_url, path.lstrip("/")),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get(self, path: str) -> dict[str, Any]:
        req = urllib.request.Request(
            urljoin(self._base_url, path.lstrip("/")),
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=self._timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))

    def lookup(
        self,
        lat: float,
        lon: float,
        *,
        mode: str | None = None,
        auto_update: bool | None = None,
    ) -> dict[str, Any]:
        return self._post(
            "/lookup",
            {
                "lat": lat,
                "lon": lon,
                "mode": mode or self._mode,
                "auto_update": self._auto_update if auto_update is None else auto_update,
            },
        )

    def info(self) -> dict[str, Any]:
        return self._get("/info")

    def bootstrap(
        self,
        iso2: str,
        *,
        force_reinstall: bool = False,
        update_to_latest: bool = False,
    ) -> dict[str, Any]:
        return self._post(
            "/bootstrap",
            {
                "iso2": iso2,
                "force_reinstall": force_reinstall,
                "update_to_latest": update_to_latest,
            },
        )

    def reinstall(self, iso2: str, *, update_to_latest: bool = False) -> dict[str, Any]:
        return self._post(
            "/reinstall",
            {"iso2": iso2, "update_to_latest": update_to_latest},
        )

