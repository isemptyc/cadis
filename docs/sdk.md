# Cadis SDK Mode

## Local SDK

```python
from cadis import CadisSDK

sdk = CadisSDK(
    cache_dir="/path/to/cadis-cache",
    allowed_iso2=["JP", "TW"],
)
out = sdk.lookup(25.0330, 121.5654)
```

### Contract

- `lookup()` is deterministic and side-effect free.
- No prompt, no implicit bootstrap/reinstall.
- Caller decides remediation by inspecting `execution` + `state`.
- SDK instances can carry an explicit cache root and dataset allowlist.
- Environment variables remain compatibility defaults when no explicit context is supplied.

## SDK Context

`CadisSDK` can be created with explicit runtime context:

```python
from cadis import CadisSDK

sdk = CadisSDK(
    cache_dir="/srv/genesis/cadis-cache",
    allowed_iso2=["JP", "TW"],
)
```

This context is used by:

- `sdk.lookup(...)`
- `sdk.info()`
- `sdk.bootstrap(...)`
- `sdk.reinstall(...)`

You can also override the context per call:

```python
sdk.lookup(35.68, 139.76, cache_dir="/tmp/alternate-cache")
sdk.info(allowed_iso2=["TW"])
```

Precedence rules:

1. per-call arguments
2. `CadisSDK(...)` constructor arguments
3. environment defaults such as `CADIS_CACHE_DIR` and `CADIS_ALLOWED_ISO2`
4. platform default cache resolution

## `lookup()` Return Value

`lookup()` returns a dictionary with this top-level shape:

```python
{
  "engine": "cadis",
  "version": "0.3.1",
  "execution": {
    "lookup_status": "ok" | "partial" | "failed",
    "resolution_state": (
      "resolved"
      | "partial"
      | "remediable_capability_gap"
      | "blocked_by_policy"
      | "terminal_non_country"
      | "invalid_input"
      | "engine_failure"
      | "unresolved_country"
    ),
    "capability_detail": (
      "supported_dataset_missing"
      | "unsupported_country"
      | "dataset_invalid"
      | "dataset_blocked_by_policy"
      | "dataset_ready_unresolved"
      | "input_invalid"
      | "non_country_world_classification"
    ) | null
  },
  "state": {
    "input": {...},    # present only for invalid input
    "world": {...},    # world-resolution status
    "dataset": {...},  # country dataset status
  },
  "result": {...} | None
}
```

### Top-Level Fields

- `engine`: always `"cadis"`.
- `version`: Cadis package version.
- `execution.lookup_status`:
  - `ok`: lookup completed successfully.
  - `partial`: lookup completed but the administrative hierarchy is incomplete.
  - `failed`: Cadis could not produce an administrative result.
- `execution.resolution_state`:
  - `resolved`: Cadis produced a successful resolved administrative result.
  - `partial`: Cadis produced a meaningful but incomplete administrative result.
  - `remediable_capability_gap`: lookup failed because current capability is insufficient but may improve with dataset installation or repair.
  - `blocked_by_policy`: lookup was denied by Cadis dataset policy.
  - `terminal_non_country`: world resolution succeeded but the point is not in a country dataset scope.
  - `invalid_input`: caller supplied invalid coordinates or non-numeric values.
  - `engine_failure`: Cadis failed before it could produce a stable semantic outcome.
  - `unresolved_country`: Cadis reached a country dataset context but did not produce an administrative result.
- `execution.capability_detail`:
  - optional narrower detail for hosts that need to distinguish specific capability cases without separately diffing `info()`
  - `supported_dataset_missing`: the country is supported by this Cadis build, but its dataset is not currently available
  - `unsupported_country`: world resolution identified a country, but this Cadis build does not currently support that ISO2 dataset
  - `dataset_invalid`: a dataset exists for the ISO2 but is not usable
  - `dataset_blocked_by_policy`: dataset access is denied by Cadis dataset policy
  - `dataset_ready_unresolved`: a ready dataset was selected but runtime still did not produce an administrative result
  - `input_invalid`: invalid caller input
  - `non_country_world_classification`: world resolution ended in a non-country classification
- `state`: operational state that explains why lookup succeeded or failed.
- `result`: administrative lookup payload on success, otherwise usually `None`.

### `state.input`

Present when the caller passes invalid coordinates or non-numeric values.

```python
{
  "input": {
    "status": "invalid"
  }
}
```

### `state.world`

Describes the world-resolution phase that runs before country dataset lookup.

Common fields:

- `status`: usually `ok` or `failed`
- `classification`: one of the world classifications returned by Cadis, such as `country`, `ocean`, `open_sea`, `antarctica`, or `unknown`
- `iso2`: present when `classification == "country"`
- `name`: present for named non-country regions such as ocean/open-sea classifications

Typical examples:

```python
{"status": "ok", "classification": "country", "iso2": "TW"}
```

```python
{"status": "ok", "classification": "ocean", "name": "Philippine Sea"}
```

```python
{"status": "failed", "classification": "unknown"}
```

### `state.dataset`

Describes the selected country dataset after world resolution has identified an ISO2 country.

Common fields:

- `status`
- `iso2`
- `dataset_dir`: present when a ready local dataset has been selected
- `detail_code`: present for some failure states such as policy denial

Dataset statuses:

- `ready`: a local dataset was found and used
- `missing`: no usable local dataset was found
- `invalid`: a local dataset exists but is not bootstrappable/usable
- `blocked`: dataset access is denied by Cadis dataset policy

Typical examples:

```python
{"status": "ready", "iso2": "TW", "dataset_dir": ".../TW/tw.admin/v1.0.0"}
```

```python
{"status": "missing", "iso2": "JP"}
```

```python
{"status": "blocked", "iso2": "JP", "detail_code": "dataset_blocked_by_policy"}
```

### `result`

When `execution.lookup_status` is `ok` or `partial`, `result` contains the interpreted administrative hierarchy produced by the runtime dataset.

The exact contents depend on the country dataset, but the JSON shape is the same as `cadis lookup <lat> <lon> --json` in CLI mode.

In practice you should expect country-level and hierarchy-style data, for example:

```python
{
  "country": {
    "level": 2,
    "name": "Japan"
  },
  "admin_hierarchy": [
    {
      "rank": 0,
      "osm_id": "jp_region_01",
      "level": 3,
      "name": "中国地方",
      "source": "admin_tree_name"
    },
    {
      "rank": 1,
      "osm_id": "jp_r3794962",
      "level": 4,
      "name": "岡山県",
      "source": "polygon"
    },
    {
      "rank": 2,
      "osm_id": "jp_r3934723",
      "level": 7,
      "name": "新見市",
      "source": "polygon"
    }
  ]
}
```

If lookup fails before runtime execution, `result` is `None`.

### Success Example

This is the same structure returned by both:

```python
sdk.lookup(35.153557004399545, 133.48428546061976)
```

and:

```bash
cadis lookup 35.153557004399545 133.48428546061976 --json
```

```python
{
  "engine": "cadis",
  "version": "0.3.1",
  "execution": {"lookup_status": "ok", "resolution_state": "resolved"},
  "state": {
    "world": {"status": "ok", "classification": "country", "iso2": "JP"},
    "dataset": {
      "status": "ready",
      "iso2": "JP",
      "dataset_dir": "/path/to/cadis-cache/JP/jp.admin/v1.0.1"
    }
  },
  "result": {
    "country": {
      "level": 2,
      "name": "Japan"
    },
    "admin_hierarchy": [
      {
        "rank": 0,
        "osm_id": "jp_region_01",
        "level": 3,
        "name": "中国地方",
        "source": "admin_tree_name"
      },
      {
        "rank": 1,
        "osm_id": "jp_r3794962",
        "level": 4,
        "name": "岡山県",
        "source": "polygon"
      },
      {
        "rank": 2,
        "osm_id": "jp_r3934723",
        "level": 7,
        "name": "新見市",
        "source": "polygon"
      }
    ]
  }
}
```

### Failure Examples

World resolved to a non-country region:

```python
{
  "engine": "cadis",
  "version": "0.3.1",
  "execution": {
    "lookup_status": "failed",
    "resolution_state": "terminal_non_country",
    "capability_detail": "non_country_world_classification"
  },
  "state": {
    "world": {
      "status": "ok",
      "classification": "open_sea",
      "name": "South China Sea"
    }
  },
  "result": None
}
```

Invalid input:

```python
{
  "engine": "cadis",
  "version": "0.3.1",
  "execution": {
    "lookup_status": "failed",
    "resolution_state": "invalid_input",
    "capability_detail": "input_invalid"
  },
  "state": {
    "input": {"status": "invalid"}
  },
  "result": None
}
```

Dataset missing:

```python
{
  "engine": "cadis",
  "version": "0.3.1",
  "execution": {
    "lookup_status": "failed",
    "resolution_state": "remediable_capability_gap",
    "capability_detail": "unsupported_country"
  },
  "state": {
    "world": {"status": "ok", "classification": "country", "iso2": "PH"},
    "dataset": {"status": "missing", "iso2": "PH"}
  },
  "result": None
}
```

Dataset blocked by policy:

```python
{
  "engine": "cadis",
  "version": "0.3.1",
  "execution": {
    "lookup_status": "failed",
    "resolution_state": "blocked_by_policy",
    "capability_detail": "dataset_blocked_by_policy"
  },
  "state": {
    "world": {"status": "ok", "classification": "country", "iso2": "JP"},
    "dataset": {
      "status": "blocked",
      "iso2": "JP",
      "detail_code": "dataset_blocked_by_policy"
    }
  },
  "result": None
}
```

## `info()` Return Value

`info()` returns dataset inventory metadata for the active Cadis context:

```python
{
  "schema_version": "1",
  "version": "0.3.0",
  "supported_iso2": ["JP", "TW"],
  "installed_iso2": ["JP"],
  "dataset_lockdown_enabled": False,
  "allowed_iso2": []
}
```

Field meanings:

- `schema_version`: response schema version for Cadis metadata.
- `version`: Cadis package version.
- `supported_iso2`: country datasets this Cadis build knows how to manage.
- `installed_iso2`: country folders currently present in the local Cadis cache.
- `dataset_lockdown_enabled`: whether a dataset allowlist policy is active.
- `allowed_iso2`: ISO2 allowlist currently permitted for serving. Empty when lockdown is disabled.

Important distinction:

- `supported_iso2` means Cadis can manage/install these datasets.
- `installed_iso2` means something for that ISO2 exists in local cache.
- `allowed_iso2` means Cadis is permitted to serve those datasets in the current process.

### `info()` With Lockdown Enabled

```python
{
  "schema_version": "1",
  "version": "0.3.0",
  "supported_iso2": ["JP", "TW"],
  "installed_iso2": ["JP", "TW"],
  "dataset_lockdown_enabled": True,
  "allowed_iso2": ["TW"]
}
```

## Dataset Installation Lifecycle

Cadis keeps lookup execution and dataset installation separate on purpose:

- `lookup()` does not install or repair datasets.
- `bootstrap()` installs or reuses a dataset so it becomes ready for lookup.
- `reinstall()` is the explicit "replace or refresh" path.

Typical flow:

```python
from cadis import CadisSDK

sdk = CadisSDK()
out = sdk.lookup(16.850848321319635, 121.15967381887826)
meta = sdk.info()
supported = set(meta["supported_iso2"])

if out["execution"]["lookup_status"] == "failed":
    ds = out.get("state", {}).get("dataset", {})
    iso2 = ds.get("iso2")
    if ds.get("status") == "missing" and iso2 in supported:
        bootstrap_out = sdk.bootstrap(iso2, update_to_latest=True)
```

### `bootstrap()` vs `reinstall()`

Use `bootstrap()` when you want Cadis to make a dataset available without forcing a replacement.

Behavior:

- validates the ISO2 input
- checks dataset policy first
- installs the dataset into cache if needed
- may reuse an already cached dataset depending on `update_to_latest` and cache state
- bootstraps the dataset so it is ready for runtime lookup

Use `reinstall()` when you want to force a reinstall of the dataset for that ISO2.

Behavior:

- same as `bootstrap()`
- always calls the force-reinstall path internally
- useful when an installed dataset is `invalid` or you want a clean refresh

Method signatures:

```python
sdk.bootstrap(
    iso2: str,
    *,
    cache_dir: str | Path | None = None,
    allowed_iso2: Iterable[str] | None = None,
    force_reinstall: bool = False,
    update_to_latest: bool = False,
)

sdk.reinstall(
    iso2: str,
    *,
    cache_dir: str | Path | None = None,
    allowed_iso2: Iterable[str] | None = None,
    update_to_latest: bool = False,
)
```

### `bootstrap()` / `reinstall()` Return Value

Both methods return the same envelope shape:

```python
{
  "engine": "cadis",
  "version": "0.3.0",
  "bootstrap_status": "ready" | "failed",
  "state": {
    "input": {...},    # invalid ISO2 input
    "dataset": {...},  # dataset readiness outcome
  },
  "dataset": {...}     # install metadata, usually present on success
}
```

Top-level fields:

- `engine`: always `"cadis"`
- `version`: Cadis package version
- `bootstrap_status`:
  - `ready`: dataset is ready for lookup after this call
  - `failed`: Cadis could not make the dataset ready
- `state`: operational status for the bootstrap attempt
- `dataset`: installation metadata from the CDN/bootstrap layer

### `state.dataset` During Bootstrap

Typical statuses:

- `ready`: dataset is installed and bootstrapped
- `missing`: no dataset directory could be resolved after install
- `invalid`: install or bootstrap completed, but the dataset is still unusable
- `blocked`: dataset policy denied access for this ISO2

Examples:

Successful bootstrap:

```python
{
  "engine": "cadis",
  "version": "0.3.0",
  "bootstrap_status": "ready",
  "state": {
    "dataset": {
      "status": "ready",
      "iso2": "JP",
      "dataset_dir": "/path/to/cadis-cache/JP/jp.admin/v1.0.1"
    }
  },
  "dataset": {
    "country_iso2": "JP",
    "dataset_id": "jp.admin",
    "dataset_version": "v1.0.1",
    "dataset_dir": "/path/to/cadis-cache/JP/jp.admin/v1.0.1",
    "used_cached_dataset": True
  }
}
```

Blocked by policy:

```python
{
  "engine": "cadis",
  "version": "0.3.0",
  "bootstrap_status": "failed",
  "state": {
    "dataset": {
      "status": "blocked",
      "iso2": "JP",
      "detail_code": "dataset_blocked_by_policy"
    }
  }
}
```

Invalid input:

```python
{
  "engine": "cadis",
  "version": "0.3.0",
  "bootstrap_status": "failed",
  "state": {
    "input": {
      "status": "invalid"
    }
  }
}
```

### Dataset Path Assignment

Cadis resolves the cache root in this order:

1. `cache_dir=` argument passed to `lookup()`, `info()`, `bootstrap()`, or `reinstall()`
2. `CadisSDK(cache_dir=...)` constructor default
3. `CADIS_CACHE_DIR` environment variable
4. platform default from `platformdirs`
5. fallback path `~/.cache/cadis`

Cadis resolves the dataset allowlist in this order:

1. `allowed_iso2=` argument passed to `lookup()`, `info()`, `bootstrap()`, or `reinstall()`
2. `CadisSDK(allowed_iso2=...)` constructor default
3. `CADIS_ALLOWED_ISO2` environment variable
4. no lockdown policy

If you do not pass explicit context, Cadis uses the SDK-level or environment-level defaults.

Example:

```python
sdk = CadisSDK(cache_dir="/data/cadis-cache")
sdk.bootstrap("JP")
```

This installs the dataset under a country/dataset/version layout:

```text
/data/cadis-cache/
  JP/
    jp.admin/
      v1.0.1/
        dataset_release_manifest.json
        runtime_policy.json
        ...
```

Important distinction:

- `cache_dir` affects `lookup()`, `info()`, `bootstrap()`, and `reinstall()`.
- `allowed_iso2` affects `lookup()`, `info()`, `bootstrap()`, and `reinstall()`.
- runtime caching is isolated by context, so two SDK instances can safely use different cache roots in one process.

That means a caller can safely create multiple isolated Cadis SDK contexts in one process. In practice, use one of these patterns:

- set a stable `cache_dir` on the SDK instance
- use per-call overrides only when you explicitly want to switch context
- keep environment variables as compatibility defaults rather than the primary control surface

### Installation Examples

Install using SDK-scoped cache location:

```python
sdk = CadisSDK(cache_dir="/srv/cadis-cache")
sdk.bootstrap("JP", update_to_latest=True)
```

Lookup from the same explicit cache root:

```python
sdk.lookup(35.153557004399545, 133.48428546061976)
```

Install into a per-call custom cache root:

```python
sdk.bootstrap("JP", cache_dir="/srv/another-cache", update_to_latest=True)
```

Force a clean reinstall:

```python
sdk.reinstall("JP", update_to_latest=True)
```

Create two isolated SDK contexts in one process:

```python
sdk_default = CadisSDK(cache_dir="/srv/cache-a")
sdk_locked = CadisSDK(cache_dir="/srv/cache-b", allowed_iso2=["TW"])

print(sdk_default.info())
print(sdk_locked.info())
```

## Explicit Remediation

```python
meta = sdk.info()
supported = set(meta["supported_iso2"])

if out["execution"]["lookup_status"] == "failed":
    ds = out.get("state", {}).get("dataset", {})
    iso2 = ds.get("iso2")
    if ds.get("status") in {"missing", "invalid"} and iso2 in supported:
        sdk.reinstall(iso2, update_to_latest=True)

    if ds.get("status") == "blocked":
        print(f"Dataset access for {iso2} is blocked by Cadis policy.")
```

## Remote SDK

```python
from cadis import CadisRemoteSDK

remote = CadisRemoteSDK("http://localhost:8080", mode="lazy", auto_update=True)
out = remote.lookup(24.5674, 121.0258)
```

### Remote Modes

- `lazy` (default): server may auto-sync supported datasets then retry.
- `strict`: explicit-control behavior (no implicit sync).
- `blocked` datasets are never auto-synced.
