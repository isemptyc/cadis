"""CGD backend selection for cadis.world."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .cgd_binary import CGDReader

BACKEND_AUTO = "auto"
BACKEND_PYTHON = "python"
BACKEND_NATIVE = "native"
SUPPORTED_BACKENDS = {BACKEND_AUTO, BACKEND_PYTHON, BACKEND_NATIVE}


def _requested_backend() -> str:
    raw = os.environ.get("CADIS_CGD_BACKEND", BACKEND_AUTO)
    backend = raw.strip().lower() if isinstance(raw, str) else BACKEND_AUTO
    if backend not in SUPPORTED_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_BACKENDS))
        raise ValueError(f"Unsupported CADIS_CGD_BACKEND={raw!r}; expected one of: {supported}")
    return backend


def _load_native_kernel() -> type[Any]:
    from cadis_native_cgd import CgdWorldKernel

    return CgdWorldKernel


def create_cgd_reader(path: Path) -> Any:
    """Create the configured CGD reader/kernel.

    ``auto`` preserves public Cadis compatibility by falling back to Python when
    the optional native module is unavailable or fails to initialize.
    """
    backend = _requested_backend()
    if backend == BACKEND_PYTHON:
        return CGDReader(path)

    if backend == BACKEND_NATIVE:
        native_kernel = _load_native_kernel()
        return native_kernel(path)

    try:
        native_kernel = _load_native_kernel()
        return native_kernel(path)
    except Exception:
        return CGDReader(path)
