# Cadis 0.8.0 Release Notes

Cadis 0.8.0 is a performance and memory optimization milestone for batch
administrative lookup workloads.

## Highlights

- Native FFSF fallback geometry is now used by default when the optional
  `cadis_native_cgd` module is installed.
- Country-scope containment, country-scope distance, feature distance, and
  nearest feature candidate queries can execute in Rust.
- Cadis skips building Python-side FFSF geometry arrays when native fallback
  geometry is active and shadow mode is disabled.
- Batch lookup keeps policy and result construction in Python while moving
  geometry facts to the native runtime.
- Shadow validation remains available for parity checks without changing
  production output.

## Performance

Native fallback geometry removes expensive Python geometry scans from
offshore, nearest, and country-scope fallback paths. Batch-heavy workloads with
many fallback geometry checks should see the largest speedups.

`CADIS_FFSF_FALLBACK_GEOMETRY=auto` is now the default:

```bash
CADIS_FFSF_FALLBACK_GEOMETRY=auto
```

In `auto` mode, Cadis uses native fallback geometry when the native module is
available and falls back to Python otherwise.

## Memory

When native fallback geometry is active, Cadis no longer builds the heavy
Python FFSF geometry structures:

- `part_bboxes`
- `geom_index`
- `ring_index`
- `geometry_data`

Cadis keeps only lightweight routing metadata needed by the Python policy
layer. This reduces load-time peak memory and allocator churn for native
deployments.

Python geometry is still retained when:

- `CADIS_FFSF_FALLBACK_GEOMETRY=python`
- native fallback geometry is unavailable in `auto` mode
- `CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW=1`

## Validation

Shadow mode runs Python and native fallback geometry facts in parallel and logs
non-identical facts without changing lookup output:

```bash
CADIS_FFSF_FALLBACK_GEOMETRY=python \
CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW=1 \
cadis lookup-many ...
```

Severity 2 and 3 shadow mismatches are logged at warning level with the marker
`[FFSFNativeFallbackGeometryShadow]`.

## Compatibility

The public Cadis package remains Python-only. Native geometry remains optional
and is intended for deployments that build and ship `cadis_native_cgd` for
their supported platforms and Python ABIs.

To force the previous Python fallback geometry path:

```bash
CADIS_FFSF_FALLBACK_GEOMETRY=python
```
