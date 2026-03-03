# Cadis CLI Mode

## Commands

```bash
cadis lookup <lat> <lon>
cadis lookup <lat> <lon> --json
cadis info
cadis info --json
```

## Behavior

- `lookup` uses the same execution path as SDK/API.
- Human mode prints `Region: ...`.
- For actionable dataset states, CLI asks for confirmation before download/reinstall.
- After successful remediation, CLI retries lookup immediately.
- Boundary notifications (ocean/unsupported) are shown without corrective prompts.

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

