# cadis

`cadis` is the public facade entrypoint of the Cadis system.

It provides a zero-configuration global lookup interface while hiding
runtime, dataset, and bootstrap orchestration details.

`cadis` is **not** a runtime, dataset engine, or CDN client.
It is a thin facade layer built on top of `cadis-global`.

---

## Install

```bash
pip install cadis
```

---

## Quick Start

```python
from cadis import lookup, info

result = lookup(25.0330, 121.5654)
print(result["lookup_status"])

print(info())
```

---

## Public API

### `lookup(lat: float, lon: float) -> dict`

Zero-configuration lookup entrypoint.

Behavior:

* Lazy initialization on first call
* No network or bootstrap work at import time
* Deterministic response envelope
* Stable public error semantics

---

### `info() -> dict`

Returns capability metadata for the current environment.

The output includes:

* `version`: public API version
* `system_iso2`: ISO2 codes available to this installation
* `offline_iso2`: ISO2 datasets currently available in local cache

Example:

```json
{
  "schema_version": "1",
  "version": "0.1.0",
  "system_iso2": ["JP", "TW"],
  "offline_iso2": ["TW"]
}
```

`info()` has no side effects and performs no network operations.

---

## Architecture

```text
cadis (facade)
  -> cadis-global
    -> cadis-runtime
      -> cadis-core + cadis-cdn
```

---

## Cache Policy

Cache directory resolution order:

1. `CADIS_CACHE_DIR` environment variable
2. OS standard cache directory (via `platformdirs`)
3. Fallback path

Examples:

* macOS: `~/Library/Caches/cadis`
* Linux: `~/.cache/cadis`
* Windows: `%LOCALAPPDATA%\\cadis\\Cache`

---

## Design Principles

* Facade-only orchestration
* Lazy initialization
* Deterministic behavior
* Minimal public surface
* Stable error contract

---

## Versioning

`cadis` version represents the public API contract.

It does **not** represent dataset version or internal runtime version.

---

## License

MIT
