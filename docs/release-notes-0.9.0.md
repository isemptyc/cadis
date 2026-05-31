# Cadis 0.9.0 Release Notes

Cadis 0.9.0 is the candidate production release for global administrative
dataset coverage.

## Highlights

- Cadis now points dataset bootstrap and reinstall flows at the production
  dataset CDN: `https://dataset.cadis.dev/releases`.
- The stable release manifest is refreshed for Cadis `0.9.0` and includes all
  195 supported ISO 3166-1 alpha-2 dataset packages.
- Dataset downloads are served from Cloudflare R2 through the Cadis dataset
  domain instead of the GitHub-hosted dataset manifest.
- Cadis CDN requests now send an explicit Cadis user agent, avoiding CDN
  rejection of Python's default `urllib` user agent.
- The stable manifest updater uses the same Cadis CDN transport path as runtime
  dataset installation.

## Dataset Coverage

This release is intended as the production candidate for all-country dataset
support.

`releases/stable.json` pins the reviewed production dataset set and records:

- Cadis package version: `0.9.0`
- Dataset manifest URL:
  `https://dataset.cadis.dev/releases/dataset_manifest.json`
- Dataset count: 195 ISO 3166-1 alpha-2 entities

Applications can continue to install datasets lazily through:

```bash
cadis lookup <lat> <lon>
```

When a supported country dataset is missing, Cadis prompts to download it from
the production dataset CDN and retries the lookup after installation.

## Operational Notes

For deployment builds that prewarm the dataset cache, continue using the stable
manifest:

```bash
./scripts/prepare_release.sh /opt/cadis-cache releases/stable.json
```

For runtime dataset refreshes, `scripts/update_stable_release_manifest.py` now
uses the same CDN transport helper as Cadis runtime downloads.

## Compatibility

Cadis 0.9.0 keeps the public CLI, SDK, REST, and cache layout compatible with
the 0.8.x line.

Existing installed datasets remain usable. New installs and reinstalls resolve
the latest reviewed dataset artifacts from the Cadis production dataset CDN.

## Verification

The release was verified with:

```bash
python -m pytest tests/test_cdn_transport.py tests/test_stable_release_manifest.py
python -m build --wheel
```

The rebuilt wheel is:

```text
dist/cadis-0.9.0-py3-none-any.whl
```
