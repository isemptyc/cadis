# Native FFSF Runtime in Cadis 0.7.1

Cadis 0.7.1 promotes native FFSF fallback geometry to the default path when
the optional `cadis_native_cgd` module is installed.

The public Cadis package remains Python-only. Native geometry is an optional
artifact for deployments that choose to build and ship it.

## Runtime Behavior

Default behavior:

```bash
CADIS_FFSF_FALLBACK_GEOMETRY=auto
```

In `auto` mode:

- if native FFSF fallback geometry is available, Cadis uses Rust for
  country-scope containment, country-scope distance, feature distance, and
  nearest feature candidate queries
- if native FFSF fallback geometry is unavailable, Cadis falls back to the
  Python geometry path
- when native fallback geometry is active and shadow mode is disabled, Cadis
  releases Python-side FFSF geometry arrays after deriving lightweight routing
  metadata

Policy interpretation and final lookup result construction remain in Python.
Rust returns geometry facts only.

## Operational Controls

Force Python fallback geometry:

```bash
CADIS_FFSF_FALLBACK_GEOMETRY=python
```

Require native fallback geometry and fail loudly if unavailable:

```bash
CADIS_FFSF_FALLBACK_GEOMETRY=native
```

Run shadow parity validation:

```bash
CADIS_FFSF_FALLBACK_GEOMETRY=python \
CADIS_FFSF_FALLBACK_GEOMETRY_SHADOW=1 \
cadis lookup-many ...
```

Shadow mode keeps production output on the selected path and executes the other
geometry path for comparison. Severity 2 and 3 mismatches are logged at warning
level with the marker `[FFSFNativeFallbackGeometryShadow]`.

Shadow mode is expected to be slower and use more memory because it retains
Python geometry and runs both Python and Rust geometry facts.

## Packaging Note

Deployments that use native geometry should build `cadis_native_cgd` for each
target platform and Python ABI they support. For example, with Python 3.12:

```bash
cd native/cadis_native_cgd
maturin build --release -i /path/to/python3.12
```

If multiple Python versions are installed, pass `-i` explicitly so maturin does
not select an unsupported interpreter.
