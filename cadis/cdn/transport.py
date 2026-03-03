from __future__ import annotations

import json
from typing import Any, Callable
from urllib.parse import urljoin, urlparse, urlunparse
import urllib.request


def repo_relative_url(base_url: str, relative_path: str) -> str:
    rel_raw = relative_path.strip()
    if rel_raw.startswith(("http://", "https://", "file://")):
        return rel_raw
    rel = rel_raw.lstrip("/")
    if rel.startswith("releases/"):
        parsed = urlparse(base_url)
        marker = "/releases/"
        if marker in parsed.path:
            prefix = parsed.path.split(marker, 1)[0].rstrip("/") + "/"
            return urlunparse(parsed._replace(path=prefix + rel))
    return urljoin(base_url, rel)


def read_json_url(url: str, *, timeout_sec: int) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout_sec) as response:
        return json.loads(response.read().decode("utf-8"))


def read_text_url(url: str, *, timeout_sec: int) -> str:
    with urllib.request.urlopen(url, timeout=timeout_sec) as response:
        return response.read().decode("utf-8")


def read_bytes_url(
    url: str,
    *,
    timeout_sec: int,
    progress: Callable[[int, int | None], None] | None = None,
    chunk_size: int = 1024 * 1024,
) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout_sec) as response:
        total: int | None = None
        length_header = response.headers.get("Content-Length")
        if length_header and length_header.isdigit():
            total = int(length_header)

        chunks: list[bytes] = []
        downloaded = 0
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            chunks.append(chunk)
            downloaded += len(chunk)
            if progress is not None:
                progress(downloaded, total)

        if progress is not None and downloaded == 0:
            progress(0, total)

        return b"".join(chunks)
