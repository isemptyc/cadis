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

## Quick Start (CLI)

```bash
cadis lookup 41.8785708032352 12.505896501941912
```

Typical flow:

- If the country dataset is already installed, Cadis prints `Region: ...` immediately.
- If the dataset is missing but supported, Cadis offers to download it and retries the lookup after install.
- Sea and offshore results are shown directly in human-readable form.

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
- Deployment guide: [`docs/deployment.md`](docs/deployment.md)
- CI/CD examples: [`docs/cicd-examples.md`](docs/cicd-examples.md)
- Stable release manifest: [`releases/stable.json`](releases/stable.json)
- Stable manifest updater: [`scripts/update_stable_release_manifest.py`](scripts/update_stable_release_manifest.py)

## Core APIs

- `lookup(lat, lon)`
- `lookup_many(points=[{"id": "...", "lat": ..., "lon": ...}])`
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
| TW   | Taiwan           | tw.admin   | 1.8 MB                | 2.0 MB        | 2026-04-05         |
| JP   | Japan            | jp.admin   | 20.4 MB               | 21.4 MB       | 2026-04-05         |
| GB   | United Kingdom   | gb.admin   | 4.8 MB                | 5.2 MB        | 2026-04-05         |
| IT   | Italy            | it.admin   | 22.9 MB               | 26.0 MB       | 2026-04-05         |
| KR   | South Korea      | kr.admin   | 2.4 MB                | 3.6 MB        | 2026-04-05         |
| SE   | Sweden           | se.admin   | 0.2 MB                | 0.3 MB        | 2026-04-05         |
| NO   | Norway           | no.admin   | 0.1 MB                | 0.3 MB        | 2026-04-05         |
| DK   | Denmark          | dk.admin   | 0.1 MB                | 0.2 MB        | 2026-04-05         |
| BE   | Belgium          | be.admin   | 2.5 MB                | 2.8 MB        | 2026-04-04         |
| NL   | Netherlands      | nl.admin   | 2.6 MB                | 2.8 MB        | 2026-04-11         |
| FR   | France           | fr.admin   | 79.6 MB               | 93.2 MB       | 2026-04-25         |

Additional ISO 3166-1 entity datasets will be published as they become available.

## License

Cadis source code is licensed under Apache License 2.0. See [`LICENSE`](LICENSE).

The bundled file [`cadis/world/data/ne.global.v0.1.0.cgd`](cadis/world/data/ne.global.v0.1.0.cgd) is transformed from Natural Earth data. Natural Earth states that its raster and vector data on the site are public domain and that no permission is needed to use it. See [`cadis/world/data/CGD_SPEC.md`](cadis/world/data/CGD_SPEC.md) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
