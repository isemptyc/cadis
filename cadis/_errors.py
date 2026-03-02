"""Stable reason normalization for cadis public envelopes."""

from __future__ import annotations

from typing import Any

KNOWN_REASONS = {
    "unsupported_country_dataset",
    "missing_dataset",
    "runtime_bootstrap_error",
    "runtime_dispatch_error",
    "runtime_invalid_response",
    "admin_interpretation_unavailable",
    "world_resolution_error",
    "invalid_input",
    "global_lookup_unavailable",
    "global_init_failed",
    "lookup_failed",
    "internal_error",
}


def normalize_reason(reason: Any) -> str:
    """Return a stable public reason code."""
    if isinstance(reason, str) and reason in KNOWN_REASONS:
        return reason

    if isinstance(reason, ValueError):
        return "invalid_input"
    if isinstance(reason, ImportError):
        return "global_lookup_unavailable"
    if isinstance(reason, RuntimeError):
        return "global_init_failed"

    if isinstance(reason, str):
        return "lookup_failed"

    return "internal_error"
