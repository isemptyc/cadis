from __future__ import annotations

import tarfile
from pathlib import Path


def safe_extract_tar_gz(archive_path: Path, target_dir: Path) -> None:
    target_resolved = target_dir.resolve()
    with tarfile.open(archive_path, mode="r:gz") as tar:
        for member in tar.getmembers():
            member_path = (target_dir / member.name).resolve()
            if not str(member_path).startswith(str(target_resolved)):
                raise ValueError(f"Unsafe tar entry path: {member.name!r}")
        tar.extractall(path=target_dir)
