# cadis

`cadis` is the single public control layer of the Cadis system.

It orchestrates:
- dataset install and bootstrap lifecycle
- world resolution and runtime execution coordination
- deterministic state to user-facing actions
- SDK + CLI + REST integration surfaces

## Install

```bash
pip install cadis
```

## Quick Start (SDK)

```python
from cadis import CadisSDK

sdk = CadisSDK()
out = sdk.lookup(25.0330, 121.5654)
print(out["execution"]["lookup_status"])
```

## Interaction Modes

- CLI guide: [`docs/cli.md`](docs/cli.md)
- SDK guide: [`docs/sdk.md`](docs/sdk.md)
- Docker/REST guide: [`docs/rest.md`](docs/rest.md)

## Core APIs

- `lookup(lat, lon)`
- `bootstrap(iso2, ...)`
- `reinstall(iso2, ...)`
- `info()`
- `CadisSDK`
- `CadisRemoteSDK`

## Architecture

```text
cadis (public control layer)
  -> world resolution (`cadis.world`)
  -> dataset install/provisioning (`cadis.cdn`)
  -> dataset bootstrap/lookup runtime (`cadis.runtime`)
  -> deterministic structural engine (`cadis.core`)
  -> remote REST surface (`cadisd`)
```

## License

MIT
