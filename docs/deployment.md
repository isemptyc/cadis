# Cadis Deployment Procedure

## Purpose

Cadis runtime lookup is deterministic for a given:

- Cadis package version
- world data shipped with that Cadis package
- installed country dataset version
- input coordinates

However, a deployment is not reproducible if it relies on:

- runtime download of whichever dataset version is latest at deploy time
- mutable cache contents carried over from older deployments
- undocumented manual dataset preparation

This document defines the official deployment procedure for Cadis when reproducibility matters.

## Deployment Principle

Production deployment should treat Cadis datasets as versioned release artifacts, not as ad hoc runtime downloads.

The recommended production rule is:

1. Pin the Cadis package version.
2. Pin every deployed dataset version.
3. Prepare datasets before deployment.
4. Deploy code and prepared datasets together.
5. Do not depend on `latest` resolution in production.

## Official Stable Manifest

Cadis should publish a repository-tracked pinned release manifest for production use.

The default production manifest is:

- `releases/stable.json`
- [CI/CD examples](./cicd-examples.md)

This manifest is the default approved release set for production. It pins:

- one Cadis package version
- one dataset version for each supported ISO2 included in the release set
- the upstream dataset manifest source and source generation timestamp used to produce the snapshot

Cadis also provides a helper to refresh this file from the upstream dataset manifest:

```bash
python scripts/update_stable_release_manifest.py
```

The intended usage is:

- fetch the upstream `dataset_manifest.json`
- snapshot the currently published latest version for each Cadis-supported ISO2
- write source timestamps into `releases/stable.json`
- review and commit the result explicitly

`stable` is not the same as `latest`:

- `latest` means most recently published dataset release
- `stable` means explicitly reviewed and approved for production deployment

Only an explicit promotion should change `stable`.

For concrete examples of Git-based CI/CD usage, artifact generation, Docker image patterns, and `stable.json` promotion, see [CI/CD examples](./cicd-examples.md).

## Deployment Modes

### Local Development

Local development may use convenience flows such as:

- `cadis lookup ...` with interactive remediation
- `cadis prepare --iso2 TW --output-dir ...` without `--dataset-version`

This mode optimizes for convenience, not reproducibility.

### Production / CI Artifact Mode

Production and release pipelines should use:

- fixed Cadis package version
- fixed dataset versions
- explicit cache root
- immutable prepared artifacts

This mode optimizes for deterministic deployment and rollback.

## Official Production Flow

### Step 1: Pin the Cadis package version

Use an explicit package version in your build:

```bash
pip install cadis==0.3.6
```

### Step 2: Define the dataset release set

Create or adopt a deployment manifest in your build system or application repository. Cadis ships a repository-tracked default stable manifest:

```json
{
  "profile": "cadis.deployment.release",
  "schema_version": 1,
  "release_name": "stable",
  "cadis_version": "0.3.6",
  "datasets": {
    "TW": "v1.0.3",
    "JP": "v1.0.4",
    "GB": "v1.0.2",
    "IT": "v1.0.2",
    "KR": "v1.0.1"
  }
}
```

This file is the authoritative definition of the deployment.

### Step 3: Prepare datasets in CI or release build

Use a dedicated cache root and pin each dataset version:

```bash
./scripts/prepare_release.sh /build/cadis-cache releases/stable.json
```

`--output-dir` is the Cadis cache root. Prepared datasets will be placed under:

```text
/build/cadis-cache/TW/tw.admin/v1.0.3
/build/cadis-cache/JP/jp.admin/v1.0.4
/build/cadis-cache/GB/gb.admin/v1.0.2
/build/cadis-cache/IT/it.admin/v1.0.2
/build/cadis-cache/KR/kr.admin/v1.0.1
```

### Step 4: Publish the prepared cache as a deployment artifact

Package the prepared cache directory as an artifact in your own build system, for example:

- Docker image layer
- tarball attached to a release
- object storage artifact
- VM image content

The important rule is that the deployed dataset set must come from the release pipeline, not from first-request runtime downloads.

### Step 5: Deploy with an explicit cache root

At runtime, point Cadis to the prepared cache:

```bash
export CADIS_CACHE_DIR=/srv/cadis/cache
```

Or pass the cache directory explicitly in SDK usage:

```python
from cadis import CadisSDK

sdk = CadisSDK(cache_dir="/srv/cadis/cache")
```

### Step 6: Optionally restrict allowed datasets

If your service should serve only a subset of prepared datasets:

```bash
export CADIS_ALLOWED_ISO2=TW,JP,GB
```

This prevents accidental use of datasets that are present but not approved for that deployment.

## Production Rules

In production, Cadis operators should follow these rules:

- Do not rely on `latest` dataset resolution.
- Do not treat interactive CLI remediation as a deployment procedure.
- Do not allow deployments to inherit unmanaged old cache contents.
- Do not mix datasets prepared by unrelated releases into the same runtime cache root.
- Do keep code version and dataset versions recorded together.

## Runtime Update Policy

Production services should prefer one of these policies:

### Strict Policy

- Datasets are prepared only in CI or release engineering.
- Runtime does not auto-install or auto-update datasets.
- Missing datasets are treated as deployment errors.

This is the preferred policy for deterministic systems.

### Controlled Rollout Policy

- Dataset updates are prepared as a new release artifact.
- Application rollout and dataset rollout happen together.
- Rollback restores both application version and dataset set.

This is the preferred policy when datasets change frequently.

## Rollback

Rollback should restore the previous pair:

- Cadis package version
- dataset release set

Example:

```json
{
  "cadis_version": "0.3.6",
  "datasets": {
    "TW": "v1.0.2",
    "JP": "v1.0.3",
    "GB": "v1.0.1"
  }
}
```

A rollback is complete only when both code and dataset artifacts are reverted to the previous release definition.

## CI Example

Example release preparation script:

```bash
#!/usr/bin/env bash
set -euo pipefail

CACHE_ROOT="${1:?cache root required}"

pip install "cadis==0.3.6"

./scripts/prepare_release.sh "$CACHE_ROOT" releases/stable.json
```

## Verification

Before shipping an artifact, verify:

- the intended Cadis version is installed
- the intended dataset directories exist under the prepared cache root
- the runtime process is configured to use that cache root
- the allowed ISO set matches the deployment policy

Useful checks:

```bash
cadis info --json
```

```bash
find /srv/cadis/cache -maxdepth 4 -type d | sort
```

## What Is Allowed To Use `latest`

Using `latest` is acceptable for:

- personal development
- exploratory QA
- one-off dataset refresh jobs where reproducibility is not required

Using `latest` is not recommended for:

- production releases
- audited environments
- CI pipelines that produce deployable artifacts

## Summary

Cadis itself can remain deterministic, but deployment is only reproducible when datasets are managed as pinned artifacts.

The official deployment procedure is therefore:

1. pin Cadis version
2. pin dataset versions
3. run `cadis prepare` during build
   preferably via a pinned manifest such as `releases/stable.json`
4. publish the prepared cache as an artifact
5. deploy with explicit cache configuration
