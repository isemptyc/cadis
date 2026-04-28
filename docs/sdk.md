# Cadis SDK Mode

## Local SDK

```python
from cadis import CadisSDK

sdk = CadisSDK(
    cache_dir="/path/to/cadis-cache",
    allowed_iso2=["JP", "TW"],
)
out = sdk.lookup(25.0330, 121.5654)
batch = sdk.lookup_many(
    points=[
        {"id": "row-1", "lat": 35.0, "lon": 139.0},
        {"id": "row-2", "lat": 56.34, "lon": 12.31},
    ],
)
```

### Contract

- `lookup()` is deterministic and side-effect free.
- `lookup_many()` preserves input order and input identity while returning the same per-point lookup payload shape as `lookup()`.
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
- `sdk.lookup_many(...)`
- `sdk.classify_world(...)`
- `sdk.info()`
- `sdk.bootstrap(...)`
- `sdk.reinstall(...)`

You can also override the context per call:

```python
sdk.lookup(35.68, 139.76, cache_dir="/tmp/alternate-cache")
sdk.lookup_many([{"id": "tokyo", "lat": 35.68, "lon": 139.76}], allowed_iso2=["JP"])
sdk.classify_world(35.68, 139.76, allowed_iso2=["JP"])
sdk.info(allowed_iso2=["TW"])
```

Precedence rules:

1. per-call arguments
2. `CadisSDK(...)` constructor arguments
3. environment defaults such as `CADIS_CACHE_DIR` and `CADIS_ALLOWED_ISO2`
4. platform default cache resolution

## `classify_world()` Return Value

Use `classify_world()` when you only need world/country classification and do not want to load a country runtime dataset.

```python
out = sdk.classify_world(25.0330, 121.5654)
```

`classify_world()` returns a dictionary with this top-level shape:

```python
{
  "engine": "cadis",
  "version": "0.5.1",
  "classification_status": "ok" | "failed",
  "state": {
    "input": {...},  # present only for invalid input
    "world": {...},  # world-resolution status
  },
  "result": {
    "world": {...}
  } | None
}
```

On successful world classification, `classification_status` is `ok` for both country and non-country classifications. For example:

```python
{
  "engine": "cadis",
  "version": "0.5.1",
  "classification_status": "ok",
  "state": {
    "world": {
      "status": "ok",
      "classification": "country",
      "iso2": "TW",
      "name": "Taiwan"
    }
  },
  "result": {
    "world": {
      "status": "ok",
      "classification": "country",
      "iso2": "TW",
      "name": "Taiwan"
    }
  }
}
```

Open sea and other terminal world regions are also successful classifications:

```python
{
  "engine": "cadis",
  "version": "0.5.1",
  "classification_status": "ok",
  "state": {
    "world": {
      "status": "ok",
      "classification": "open_sea",
      "name": "South Atlantic Ocean"
    }
  },
  "result": {
    "world": {
      "status": "ok",
      "classification": "open_sea",
      "name": "South Atlantic Ocean"
    }
  }
}
```

`classify_world()` does not inspect, install, bootstrap, or load country datasets. Use it before `lookup()` when a caller wants to group or filter many points by world ISO2 without warming country runtimes.

## `lookup()` Return Value

`lookup()` returns a dictionary with this top-level shape:

```python
{
  "engine": "cadis",
  "version": "0.5.1",
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

## `lookup_many()` Return Value

`lookup_many()` accepts iterable point dictionaries with `id`, `lat`, and `lon` fields:

```python
out = sdk.lookup_many(
    points=[
        {"id": "row-id-1", "lat": 35.0, "lon": 139.0},
        {"id": "row-id-2", "lat": 56.34, "lon": 12.31},
    ],
    allowed_iso2=["JP", "SE", "DK"],
)
```

It returns one item per input point, in the same order:

```python
[
  {"id": "row-id-1", "lookup": {...}},
  {"id": "row-id-2", "lookup": {...}},
]
```

Each `lookup` value is the same payload schema returned by `lookup()`. Invalid point dictionaries produce a failed lookup payload with `resolution_state="invalid_input"` and preserve the row identity.

`lookup_many()` performs deterministic batch planning internally. Cadis validates inputs, runs a world pass, resolves open-sea/offshore candidates, groups resolvable rows by ISO2, processes country groups in stable order, and writes results back to the original input order.

Cadis guarantees cache-state invariance for a stable runtime environment. Stable means dataset files and versions do not change during the process lifetime, backend selection and related environment configuration remain fixed, and runtime initialization behavior is consistent without transient failures. Under those conditions, lookup results depend only on input data and installed datasets, not on whether country runtimes are cold, warm, retained, or released.

`lookup_many()` cache behavior is a performance policy, not a semantic policy. `runtime_cache_policy="batch"` may release country runtimes after each group, while `runtime_cache_policy="cache"` may retain them for reuse; both modes must produce identical lookup payloads for the same inputs in a stable environment. `CADIS_RUNTIME_CACHE_SIZE=0` disables residual country runtime retention and is useful as a canonical cold-cache reference path for debugging.

Country runtime batch execution is also a performance policy. `CADIS_COUNTRY_RUNTIME_BATCH=off` is the default and uses the scalar country runtime path. Set `CADIS_COUNTRY_RUNTIME_BATCH=auto` to use the country runtime batch path only for sufficiently large same-country groups, controlled by `CADIS_COUNTRY_RUNTIME_BATCH_MIN_ROWS` with default `256`, or `on` to force batch execution. This path is most useful for large same-country batches, such as country dataset evaluation or bulk imports where most points resolve to one ISO2. It may provide little benefit for mixed-country workloads dominated by runtime loading, offshore/nearest fallback, or many small country groups.

Set `CADIS_LOOKUP_TRACE=1` to emit one JSON timing line per `lookup_many()` call on stderr. The trace includes world, offshore, grouping, country runtime readiness, scalar/batch runtime execution, and result-finalization timings.

If dataset files change, backend configuration changes, or runtime initialization becomes unstable during a process, cold and warm behavior can diverge. Cadis treats that as an operational consistency issue rather than supported semantic behavior.

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
  "version": "0.5.1",
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
  "version": "0.5.1",
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
  "version": "0.5.1",
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
  "version": "0.5.1",
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
  "version": "0.5.1",
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
  "version": "0.5.1",
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
  "version": "0.5.1",
  "supported_iso2": ["JP", "TW"],
  "installed_iso2": ["JP", "TW"],
  "dataset_lockdown_enabled": True,
  "allowed_iso2": ["TW"]
}
```

## Dataset Installation Lifecycle

Cadis keeps lookup execution and dataset installation separate on purpose:

- `lookup()` does not install or repair datasets.
- `classify_world()` does not inspect or load country datasets.
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
  "version": "0.5.1",
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
  "version": "0.5.1",
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
  "version": "0.5.1",
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
  "version": "0.5.1",
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

1. `cache_dir=` argument passed to `lookup()`, `lookup_many()`, `classify_world()`, `info()`, `bootstrap()`, or `reinstall()`
2. `CadisSDK(cache_dir=...)` constructor default
3. `CADIS_CACHE_DIR` environment variable
4. platform default from `platformdirs`
5. fallback path `~/.cache/cadis`

Cadis resolves the dataset allowlist in this order:

1. `allowed_iso2=` argument passed to `lookup()`, `lookup_many()`, `classify_world()`, `info()`, `bootstrap()`, or `reinstall()`
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

- `cache_dir` affects `lookup()`, `classify_world()`, `info()`, `bootstrap()`, and `reinstall()`.
- `allowed_iso2` affects `lookup()`, `classify_world()`, `info()`, `bootstrap()`, and `reinstall()`.
- country runtime caching is isolated by context, so two SDK instances can safely use different cache roots in one process.
- the world resolver is shared across manager contexts in the same process.

That means a caller can safely create multiple isolated Cadis SDK contexts in one process. In practice, use one of these patterns:

- set a stable `cache_dir` on the SDK instance
- use per-call overrides only when you explicitly want to switch context
- keep environment variables as compatibility defaults rather than the primary control surface

### Runtime Loading Behavior

Cadis loads country runtimes lazily. A normal country `lookup()` loads the selected ISO2 runtime when that dataset is ready and not already resident in the active context.

`classify_world()` only runs world classification and never loads country runtimes.

For open-sea/offshore points, `lookup()` uses a deterministic lightweight candidate selector before loading country runtimes. Candidate selection reads dataset policy and country-scope bbox metadata, applies the active allowlist policy, expands country-scope bboxes by `offshore_max_distance_km` plus a safety margin, sorts candidates by point-to-bbox distance and ISO2, then loads only the bounded candidate set for the authoritative runtime offshore check.

Candidate selection does not depend on which runtimes are already loaded, so open-sea attribution is independent of row order and warm/cold manager state.

The default candidate safety margin is `5` km. Override with:

```bash
CADIS_OFFSHORE_CANDIDATE_MARGIN_KM=10
```

The default maximum candidate count is `5`. Override with:

```bash
CADIS_OFFSHORE_MAX_CANDIDATES=8
```

Increasing the candidate count favors recall at the cost of loading more country runtimes for open-sea/offshore points.

### Runtime Cache Profiles

Cadis defaults to a memory-protective runtime profile. It keeps at most six country runtimes resident and automatically releases runtimes after `lookup_many()` country groups when a batch touches more than three ISO2 groups:

```bash
CADIS_RUNTIME_CACHE_SIZE=6
CADIS_BATCH_AUTO_RELEASE_THRESHOLD=3
CADIS_COUNTRY_RUNTIME_BATCH=off
```

This profile is appropriate for broad or memory-constrained workloads where a batch can touch many countries and unbounded runtime retention would create high peak RSS. The trade-off is repeated runtime loading in multi-batch workflows.

For repeated multi-batch processing where the same country set is reused and memory headroom is available, use a performance profile:

```bash
CADIS_RUNTIME_CACHE_SIZE=32
CADIS_BATCH_AUTO_RELEASE_THRESHOLD=999
CADIS_COUNTRY_RUNTIME_BATCH=off
```

This retains more country runtimes between batches and avoids runtime churn. It is faster for reuse-heavy workloads but uses more memory. Use `CADIS_RUNTIME_CACHE_SIZE=-1` only when unbounded runtime retention is explicitly acceptable.

For high-volume workloads, prefer:

```python
world = sdk.classify_world(lat, lon)
iso2 = world.get("state", {}).get("world", {}).get("iso2")

if iso2:
    out = sdk.lookup(lat, lon)
```

Batch callers can use `classify_world()` first to group or filter points before performing administrative lookups.

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
