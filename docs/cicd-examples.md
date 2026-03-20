# Cadis CI/CD Examples

This document shows practical ways to use:

- [releases/stable.json](/Users/isempty/Projects/my_cadis/cadis/releases/stable.json)
- [scripts/prepare_release.sh](/Users/isempty/Projects/my_cadis/cadis/scripts/prepare_release.sh)

These examples assume that Git is the source of truth for:

- Cadis code
- the approved stable release set
- the deployment procedure

The prepared dataset cache itself should not be stored in Git.

## GitHub Actions: Build Cache Artifact

This example checks out a tagged or pinned revision, prepares the cache from `releases/stable.json`, and uploads the prepared cache as a workflow artifact.

```yaml
name: build-cadis-cache

on:
  workflow_dispatch:
  push:
    tags:
      - "v*"

jobs:
  build-cache:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Cadis from repo
        run: pip install .

      - name: Prepare stable dataset cache
        run: ./scripts/prepare_release.sh "$RUNNER_TEMP/cadis-cache" releases/stable.json

      - name: Archive cache
        run: |
          tar -C "$RUNNER_TEMP" -czf cadis-cache.tar.gz cadis-cache

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: cadis-cache
          path: cadis-cache.tar.gz
```

## GitHub Actions: Build Docker Image With Prepared Cache

This example prepares the cache in CI first, then includes it in the image build context.

```yaml
name: build-cadis-image

on:
  workflow_dispatch:
  push:
    branches:
      - main

jobs:
  docker:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Cadis from repo
        run: pip install .

      - name: Prepare stable dataset cache
        run: ./scripts/prepare_release.sh ./cadis-cache releases/stable.json

      - name: Build image
        run: docker build -t cadis:stable .
```

## Dockerfile Pattern

One practical pattern is to prepare the cache outside the Docker build, then copy it into the image.

Example:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CADIS_CACHE_DIR=/opt/cadis-cache

WORKDIR /app

COPY . /app
COPY cadis-cache /opt/cadis-cache

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["cadisd", "--host", "0.0.0.0", "--port", "8080"]
```

This gives you:

- code from the current Git revision
- dataset cache prepared from the pinned stable manifest
- no production dependency on `latest`

## Alternative Docker Pattern: Multi-Stage Build

If you prefer to prepare datasets inside the Docker build, use a build stage that reads the same pinned manifest.

```dockerfile
FROM python:3.12-slim AS prepare

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .
RUN ./scripts/prepare_release.sh /opt/cadis-cache releases/stable.json

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CADIS_CACHE_DIR=/opt/cadis-cache

WORKDIR /app

COPY . /app
COPY --from=prepare /opt/cadis-cache /opt/cadis-cache

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["cadisd", "--host", "0.0.0.0", "--port", "8080"]
```

This is reproducible as long as:

- the build runs from a pinned Git revision or release tag
- `releases/stable.json` is reviewed and committed
- dataset versions in the manifest are pinned

## Promotion Workflow For `stable.json`

Recommended release governance:

1. New dataset releases become available upstream.
2. A maintainer updates a candidate manifest or opens a PR changing `releases/stable.json`.
3. CI prepares datasets from that proposed manifest.
4. Validation runs against the prepared cache.
5. Reviewers approve the PR.
6. The merged manifest becomes the new production default.

This keeps `stable` explicit and reviewable in Git history.

## Suggested Promotion Rules

- Treat `releases/stable.json` changes as release-management changes.
- Require PR review before changing pinned versions.
- Prefer tagging the repo after a `stable.json` promotion.
- Keep release notes that mention both Cadis version and dataset version changes.

## Rollback Workflow

If a production issue appears after promotion:

1. revert or cherry-pick back to the previous manifest commit
2. rerun cache preparation from the previous manifest
3. redeploy the previous cache artifact and app release together

The main point is that rollback should be based on a previous Git-tracked manifest, not on guesswork about what `latest` used to mean.
