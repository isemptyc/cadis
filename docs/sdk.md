# Cadis SDK Mode

## Local SDK

```python
from cadis import CadisSDK

sdk = CadisSDK()
out = sdk.lookup(25.0330, 121.5654)
```

### Contract

- `lookup()` is deterministic and side-effect free.
- No prompt, no implicit bootstrap/reinstall.
- Caller decides remediation by inspecting `execution` + `state`.

## Explicit Remediation

```python
meta = sdk.info()
supported = set(meta["supported_iso2"])

if out["execution"]["lookup_status"] == "failed":
    ds = out.get("state", {}).get("dataset", {})
    iso2 = ds.get("iso2")
    if ds.get("status") in {"missing", "invalid"} and iso2 in supported:
        sdk.reinstall(iso2, update_to_latest=True)
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

