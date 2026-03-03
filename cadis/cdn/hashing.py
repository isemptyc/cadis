from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_checksum_from_files(checksums: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(checksums.keys()):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(checksums[rel].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def parse_sha256_file(raw: str) -> str:
    token = raw.strip().split()[0] if raw.strip() else ""
    if len(token) != 64 or any(c not in "0123456789abcdefABCDEF" for c in token):
        raise ValueError("Invalid sha256 file content for dataset package.")
    return token.lower()
