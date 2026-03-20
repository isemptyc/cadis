#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 OUTPUT_DIR [MANIFEST_PATH]" >&2
  exit 1
fi

OUTPUT_DIR="$1"
MANIFEST_PATH="${2:-releases/stable.json}"

mkdir -p "$OUTPUT_DIR"

python - "$MANIFEST_PATH" <<'PY' | while IFS=$'\t' read -r iso2 version; do
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
payload = json.loads(manifest_path.read_text())

profile = payload.get("profile")
if profile != "cadis.deployment.release":
    raise SystemExit(f"Unsupported manifest profile: {profile!r}")

schema_version = payload.get("schema_version")
if schema_version != 1:
    raise SystemExit(f"Unsupported manifest schema_version: {schema_version!r}")

datasets = payload.get("datasets")
if not isinstance(datasets, dict) or not datasets:
    raise SystemExit("Manifest datasets must be a non-empty object.")

for iso2, version in datasets.items():
    if not isinstance(iso2, str) or not iso2.strip():
        raise SystemExit("Manifest dataset ISO2 keys must be non-empty strings.")
    if not isinstance(version, str) or not version.strip():
        raise SystemExit(f"Manifest dataset version for {iso2!r} must be a non-empty string.")
    print(f"{iso2.strip().upper()}\t{version.strip()}")
PY
  echo "Preparing ${iso2} ${version} into ${OUTPUT_DIR}"
  cadis prepare \
    --iso2 "$iso2" \
    --dataset-version "$version" \
    --output-dir "$OUTPUT_DIR"
done

echo "Prepared release manifest ${MANIFEST_PATH} into ${OUTPUT_DIR}"
