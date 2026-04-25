Third-Party Notices
===================

This repository and its distribution artifacts may include the following
third-party material:

1. Natural Earth-derived world dataset

Included file:
- `cadis/world/data/ne.global.v0.1.0.cgd`

Source:
- Natural Earth
- https://www.naturalearthdata.com

Status:
- The Natural Earth Terms of Use state that all versions of Natural Earth
  raster and vector map data on the website are in the public domain.
- The Terms of Use further state that no permission is needed to use Natural
  Earth data and crediting the authors is unnecessary.

This notice is included for provenance clarity because Cadis distributes a
transformed dataset derived from Natural Earth. It does not change the public
domain status stated by Natural Earth for that source data.

2. Optional native CGD Rust extension dependencies

Included source package:
- `native/cadis_native_cgd`

Status:
- This optional native extension is provided for sealed runtime packaging, and is not part of the default Cadis PyPI distribution.
- The extension is licensed under Apache License 2.0 as part of this
  repository.
- Its Rust dependency set is pinned in
  `native/cadis_native_cgd/Cargo.lock`.
- Runtime distributions that build and ship this native extension should
  include third-party notices generated from the locked Cargo dependency
  metadata for that distribution artifact.

Primary Rust dependency:
- PyO3
- https://pyo3.rs/
