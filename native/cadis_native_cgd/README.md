# cadis_native_cgd

Optional native CGD kernel for sealed runtimes that package their own native
artifacts. The public Cadis PyPI package does not depend on this module.

Cadis discovers this module only when `CADIS_CGD_BACKEND` allows native use:

```text
CADIS_CGD_BACKEND=auto    # try native, fall back to Python
CADIS_CGD_BACKEND=python  # force Python CGDReader
CADIS_CGD_BACKEND=native  # require this module
```

Python contract:

```python
from cadis_native_cgd import CgdWorldKernel

kernel = CgdWorldKernel("/path/to/ne.global.v0.1.0.cgd")
kernel.lookup(lon, lat)                  # dict | None
kernel.lookup_many_lons_lats(lons, lats) # list[dict | None]
```

Build in an environment with Rust and maturin:

```bash
cd native/cadis_native_cgd
python -m pip install maturin
maturin develop --release
```

Then run the small public parity check:

```bash
python native/cadis_native_cgd/scripts/compare_parity.py \
  --cgd cadis/world/data/ne.global.v0.1.0.cgd
```

Phase 1 intentionally uses the same CGD file and same linear scan/precedence
behavior as `cadis.world.cgd_binary.CGDReader`. It does not add a spatial index.
