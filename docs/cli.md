# Cadis CLI Mode

## Commands

```bash
cadis lookup <lat> <lon>
cadis lookup <lat> <lon> --json
cadis info
cadis info --json
cadis prepare --iso2 TW --output-dir /path/to/dataset
cadis prepare --iso2 TW --dataset-version v1.0.3 --output-dir /path/to/dataset
```

## Behavior

- `lookup` uses the same execution path as SDK/API.
- Human mode prints `Region: ...`.
- For actionable dataset states, CLI asks for confirmation before download/reinstall.
- After successful remediation, CLI retries lookup immediately.
- Boundary notifications (ocean/unsupported) are shown without corrective prompts.
- `prepare` downloads a country dataset into the exact directory passed by `--output-dir`.
- `prepare` uses `--output-dir` as the Cadis cache root and installs the dataset using the same bootstrap path that runtime remediation uses.
- `prepare --iso2` is required.
- `prepare --dataset-version` is optional; when omitted, Cadis resolves the latest published version.
- `prepare --output-dir` is required.

## Examples

```bash
cadis lookup 24.567439426864148 121.02576600335526
```

```bash
cadis lookup 25.980103337049524 143.83473058077158
```

```bash
cadis lookup 25.0330 121.5654 --json
```

```bash
cadis info
```

```bash
cadis prepare --iso2 TW --dataset-version v1.0.3 --output-dir /path/to/dataset
```
