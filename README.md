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

## Dataset Lockdown

By default, Cadis serves lookups from any installed dataset in the cache folder.

To restrict serving to a subset of installed country datasets, set:

```bash
export CADIS_ALLOWED_ISO2=TW,JP
```

When enabled, Cadis fails lookups outside the allowlist with `state.dataset.status = "blocked"` and refuses bootstrap/reinstall for those countries.

## Architecture

```text
cadis (public control layer)
  -> world resolution (`cadis.world`)
  -> dataset install/provisioning (`cadis.cdn`)
  -> dataset bootstrap/lookup runtime (`cadis.runtime`)
  -> deterministic structural engine (`cadis.core`)
  -> remote REST surface (`cadisd`)
```

## ISO Code Policy

Cadis uses ISO 3166-1 alpha-2 codes as technical identifiers.

These codes are interpreted strictly according to the ISO 3166 standard and are used solely for data partitioning and administrative dataset selection.

Cadis does not interpret ISO codes as political statements or sovereignty declarations.

---

## Supported ISO 3166-1 Entities

| ISO2 | Name             | Dataset ID | Package Size (tar.gz) | Unpacked Size | Release Date (UTC) |
|:-----|:---------------- |:-----------|----------------------:|--------------:|-------------------:|
| TW   | Taiwan           | tw.admin   | 1.8 MB                | 2.0 MB        | 2026-02-28         |
| JP   | Japan            | jp.admin   | 20.4 MB               | 21.3 MB       | 2026-03-05         |
| GB   | United Kingdom   | gb.admin   | 4.8 MB                | 5.1 MB        | 2026-03-11         |
| IT   | Italy            | it.admin   | 22.8 MB               | 25.7 MB       | 2026-03-11         |
| KR   | South Korea      | kr.admin   | 2.3 MB                | 3.1 MB        | 2026-03-12         |

Additional ISO 3166-1 entity datasets will be published as they become available.

## License

MIT
