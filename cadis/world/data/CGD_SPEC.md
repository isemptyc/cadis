# CGD - Cadis Global Dataset

Binary Specification v0.1 (Refined Draft)

Attribution:

This product includes data from Natural Earth (public domain).
https://www.naturalearthdata.com

## 1. Design Goals

CGD is for:

- country-level polygon lookup (ISO2 routing)
- ocean/open-sea semantic labeling
- land/ocean mask semantics for global orchestration

CGD is not for:

- multi-level administrative hierarchy inference
- geometry repair at runtime
- arbitrary GIS/spatial query workloads

Core philosophy:

> Minimal deterministic spatial contract for cadis.world runtime.

## 2. File Layout Overview

Single `.cgd` file:

```text
[Header: fixed 64 bytes]
[Polygon Index Table]
[Bounding Box Table]
[Geometry Blob]
[String Offset Table]
[String Blob]
```

Encoding rules:

- little-endian
- coordinates: float32
- counts/indexes: uint32 (unless noted)
- file offsets: uint64 (absolute offsets from file start)

## 3. Header (Fixed 64 Bytes)

| Offset | Size | Type     | Description |
| --- | --- | --- | --- |
| 0  | 8  | byte[8] | Magic bytes = `43 47 44 01 00 00 00 00` (`CGD` + version marker) |
| 8  | 2  | uint16  | `spec_major` (1) |
| 10 | 2  | uint16  | `spec_minor` (0) |
| 12 | 4  | uint32  | polygon_count |
| 16 | 4  | uint32  | string_count |
| 20 | 4  | uint32  | reserved |
| 24 | 8  | uint64  | offset_polygon_index |
| 32 | 8  | uint64  | offset_bbox_table |
| 40 | 8  | uint64  | offset_geometry_blob |
| 48 | 8  | uint64  | offset_string_offset_table |
| 56 | 8  | uint64  | offset_string_blob |

Header validation requirements:

- all offsets must be monotonic and within file length
- `polygon_count` must match polygon index + bbox rows
- `string_count` must match string offset table rows

## 4. Polygon Index Table

Each polygon record is fixed-size.

| Field | Type | Description |
| --- | --- | --- |
| bbox_index | uint32 | index into bounding box table |
| geom_offset | uint64 | absolute offset to polygon geometry payload |
| ring_count | uint32 | number of rings in this polygon |
| string_index | uint32 | primary display name index |
| iso2_code | char[2] | ISO 3166-1 alpha-2, or `00 00` when not applicable |
| terminal_code | uint8 | 0=none, 1=open_sea, 2=antarctica, 3=no_sovereign_land |
| flags | uint16 | bit flags |
| reserved | uint8 | reserved |

Flags definition (`uint16`):

- bit 0: country polygon
- bit 1: ocean polygon
- bit 2: landmass polygon
- bit 3: terminal_world semantic polygon
- bits 4-15: reserved

Notes:

- `geom_offset` is always absolute file offset (not relative).
- multipolygon geometries must be flattened at build time into multiple polygon rows.
- flattened rows may share `iso2_code`, `terminal_code`, and `string_index`.

## 5. Bounding Box Table

One row per polygon.

| Field | Type |
| --- | --- |
| min_lon | float32 |
| min_lat | float32 |
| max_lon | float32 |
| max_lat | float32 |

Runtime first-stage filter:

```python
if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
    skip
```

## 6. Geometry Blob

Polygon payload format at `geom_offset`:

```text
ring_count:uint32
repeat ring_count times:
  point_count:uint32
  repeat point_count times:
    lon:float32
    lat:float32
```

Rules:

- first ring is outer ring; subsequent rings are holes
- WGS84 (EPSG:4326)
- no self-intersection after build normalization
- minimum 4 points per closed ring (first point = last point)
- runtime never repairs invalid geometry

Multipolygon policy:

- build phase must flatten multipolygon into independent polygon records
- no nested collection type appears in runtime payload

## 7. String Storage

String Offset Table (`string_count` rows):

| Field | Type | Description |
| --- | --- | --- |
| str_offset | uint64 | absolute offset into String Blob |
| str_length | uint32 | UTF-8 byte length |
| reserved | uint32 | reserved |

String Blob:

- raw UTF-8 bytes
- no terminator required

Typical values:

- country short/long names
- ocean names
- terminal label names

## 8. Runtime Lookup Contract

Deterministic lookup loop:

```python
for i in polygon_order:
    bbox = bbox_table[index[i].bbox_index]
    if not point_in_bbox(lon, lat, bbox):
        continue
    geom = read_geometry(index[i].geom_offset)
    if point_in_polygon_covers(lon, lat, geom):
        return metadata(i)
return terminal_open_sea_or_no_match_policy
```

Boundary semantics:

- point-in-polygon must use `covers` semantics (boundary-inclusive)
- this is mandatory to avoid border-point instability

No runtime spatial tree in v0.1:

- no R-tree
- no hierarchy inference
- linear scan with bbox short-circuit is acceptable for small polygon count

## 9. Polygon Ordering

`polygon_order` must be deterministic and defined by build pipeline:

1. terminal polygons last
2. country polygons before ocean polygons
3. stable tie-breaker: `iso2_code`, then `string_index`, then original source feature id

This ensures reproducible behavior when polygons overlap.

## 10. Dataset Manifest (Recommended)

`manifest.json` example:

```json
{
  "dataset_id": "ne.global",
  "dataset_version": "v1.0.0",
  "geometry_format": "CGD-v1",
  "spec_version": "1.0",
  "source": "Natural Earth 5.1.2",
  "resolution": "10m",
  "license": "Public Domain",
  "polygon_count": 245,
  "string_count": 420,
  "point_in_polygon_rule": "covers_even_odd",
  "antimeridian_policy": "split_in_build",
  "ring_orientation": "normalized_ccw_outer_cw_hole",
  "sha256": "<hex>"
}
```

## 11. Build Pipeline

```text
Natural Earth shapefile(s)
  -> cadis.world-dataset-engine
  -> geometry validation + normalization
  -> multipolygon flattening
  -> ring orientation normalization
  -> bbox precompute
  -> CGD binary write
  -> SHA256 compute
  -> manifest emit
  -> publish to CDN
```

Runtime constraints:

- runtime never reads shapefile directly
- runtime only consumes `.cgd` + manifest

## 12. Compatibility and Evolution

v0.1 compatibility rules:

- readers must reject unknown `spec_major`
- readers may accept higher `spec_minor` if required fields are compatible
- reserved bits/fields must be written as zero and ignored when reading

Planned future extensions:

- optional per-file index acceleration block
- optional compressed geometry sections
- optional multilingual string map

## 13. Cadis Boundary Alignment

- `cadis.world-dataset`: dataset schema + build artifacts
- `cadis.world`: world orchestration + runtime routing
- `cadis.runtime`: country dataset interpreter (admin hierarchy), unchanged semantics
- `cadis.cdn`: transport/bootstrap/integrity channel for CGD package delivery

## 14. Project and Distribution Policy

- `cadis.world-dataset` is an internal Cadis project and is not published to GitHub.
- Generated CGD artifacts (for example `ne.global.v0.1.0.cgd`) are released and distributed together with `cadis.world`.

## 15. Attribution and License Notice

This product includes data from Natural Earth (public domain).
https://www.naturalearthdata.com
