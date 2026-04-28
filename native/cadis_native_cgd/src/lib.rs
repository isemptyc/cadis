use pyo3::exceptions::{PyFileNotFoundError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

const CGD_MAGIC: &[u8; 8] = b"CGD\x01\x00\x00\x00\x00";
const SPEC_MAJOR: u16 = 1;

const HEADER_SIZE: usize = 64;
const POLYGON_INDEX_SIZE: usize = 26;
const BBOX_SIZE: usize = 16;
const STRING_OFFSET_SIZE: usize = 16;

const FLAG_COUNTRY: u16 = 1 << 0;
const FLAG_OCEAN: u16 = 1 << 1;
const TERMINAL_OPEN_SEA: u8 = 1;

const FFSF_HEADER_SIZE: usize = 16;
const FFSF_FEATURE_INDEX_SIZE: usize = 16;
const FFSF_PART_BBOX_SIZE: usize = 16;
const FFSF_GEOM_INDEX_SIZE: usize = 16;

#[pyclass]
struct CgdWorldKernel {
    kernel: CgdKernel,
}

#[pymethods]
impl CgdWorldKernel {
    #[new]
    fn new(py: Python<'_>, cgd_path: &Bound<'_, PyAny>) -> PyResult<Self> {
        let os = py.import_bound("os")?;
        let path_obj = os.call_method1("fspath", (cgd_path,))?;
        let cgd_path = PathBuf::from(path_obj.extract::<String>()?);
        let data = fs::read(&cgd_path).map_err(|err| {
            if err.kind() == std::io::ErrorKind::NotFound {
                PyFileNotFoundError::new_err(format!("CGD file not found: {}", cgd_path.display()))
            } else {
                PyValueError::new_err(format!(
                    "Failed to read CGD file {}: {err}",
                    cgd_path.display()
                ))
            }
        })?;
        Ok(Self {
            kernel: CgdKernel::from_bytes(data)?,
        })
    }

    #[getter]
    fn backend_name(&self) -> &'static str {
        "native"
    }

    fn lookup(&self, py: Python<'_>, lon: f64, lat: f64) -> PyResult<PyObject> {
        let hit = self.kernel.lookup_many_indices(&[lon], &[lat])[0];
        self.hit_to_py(py, hit)
    }

    fn lookup_many_lons_lats(
        &self,
        py: Python<'_>,
        lons: &Bound<'_, PyAny>,
        lats: &Bound<'_, PyAny>,
    ) -> PyResult<PyObject> {
        let lon_values = extract_f64_values(lons)?;
        let lat_values = extract_f64_values(lats)?;
        if lon_values.len() != lat_values.len() {
            return Err(PyValueError::new_err(
                "lons and lats must have the same length",
            ));
        }

        let out = PyList::empty_bound(py);
        for hit in self.kernel.lookup_many_indices(&lon_values, &lat_values) {
            out.append(self.hit_to_py(py, hit)?)?;
        }
        Ok(out.into_py(py))
    }
}

impl CgdWorldKernel {
    fn hit_to_py(&self, py: Python<'_>, hit: Option<usize>) -> PyResult<PyObject> {
        let Some(polygon_index) = hit else {
            return Ok(py.None());
        };
        let polygon = &self.kernel.polygons[polygon_index];
        let dict = PyDict::new_bound(py);
        dict.set_item("polygon_index", polygon_index)?;
        match &polygon.iso2 {
            Some(iso2) => dict.set_item("iso2_code", iso2)?,
            None => dict.set_item("iso2_code", py.None())?,
        }
        dict.set_item("terminal_code", polygon.terminal_code)?;
        dict.set_item("flags", polygon.flags)?;
        dict.set_item("name", &polygon.name)?;
        Ok(dict.into_py(py))
    }
}

#[pymodule]
fn cadis_native_cgd(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<CgdWorldKernel>()?;
    m.add_class::<FfsfRuntimeKernel>()?;
    Ok(())
}

struct CgdKernel {
    polygons: Vec<Polygon>,
    rings: Vec<Ring>,
    points: Vec<Point>,
}

#[derive(Clone)]
struct Polygon {
    bbox: BBox,
    ring_start: usize,
    ring_count: usize,
    iso2: Option<String>,
    terminal_code: u8,
    flags: u16,
    name: String,
}

#[derive(Clone, Copy)]
struct Ring {
    point_start: usize,
    point_count: usize,
}

#[derive(Clone, Copy)]
struct Point {
    lon: f64,
    lat: f64,
}

#[derive(Clone, Copy)]
struct BBox {
    min_lon: f64,
    min_lat: f64,
    max_lon: f64,
    max_lat: f64,
}

struct IndexRec {
    bbox_index: usize,
    geom_offset: usize,
    ring_count: usize,
    string_index: usize,
    iso2: Option<String>,
    terminal_code: u8,
    flags: u16,
}

impl CgdKernel {
    fn from_bytes(data: Vec<u8>) -> PyResult<Self> {
        if data.len() < HEADER_SIZE {
            return Err(PyValueError::new_err("CGD file too small"));
        }
        if &data[0..8] != CGD_MAGIC {
            return Err(PyValueError::new_err("Invalid CGD magic"));
        }

        let spec_major = read_u16(&data, 8)?;
        if spec_major != SPEC_MAJOR {
            return Err(PyValueError::new_err(format!(
                "Unsupported CGD spec major: {spec_major}"
            )));
        }

        let polygon_count = read_u32(&data, 12)? as usize;
        let string_count = read_u32(&data, 16)? as usize;
        let offset_polygon_index = read_u64(&data, 24)? as usize;
        let offset_bbox_table = read_u64(&data, 32)? as usize;
        let offset_string_offset_table = read_u64(&data, 48)? as usize;

        let mut indexes = Vec::with_capacity(polygon_count);
        let mut cursor = offset_polygon_index;
        for _ in 0..polygon_count {
            require_range(&data, cursor, POLYGON_INDEX_SIZE)?;
            let bbox_index = read_u32(&data, cursor)? as usize;
            let geom_offset = read_u64(&data, cursor + 4)? as usize;
            let ring_count = read_u32(&data, cursor + 12)? as usize;
            let string_index = read_u32(&data, cursor + 16)? as usize;
            let iso2 = decode_iso2(&data[cursor + 20..cursor + 22]);
            let terminal_code = data[cursor + 22];
            let flags = read_u16(&data, cursor + 23)?;
            indexes.push(IndexRec {
                bbox_index,
                geom_offset,
                ring_count,
                string_index,
                iso2,
                terminal_code,
                flags,
            });
            cursor += POLYGON_INDEX_SIZE;
        }

        let mut bboxes = Vec::with_capacity(polygon_count);
        cursor = offset_bbox_table;
        for _ in 0..polygon_count {
            require_range(&data, cursor, BBOX_SIZE)?;
            bboxes.push(BBox {
                min_lon: read_f32(&data, cursor)? as f64,
                min_lat: read_f32(&data, cursor + 4)? as f64,
                max_lon: read_f32(&data, cursor + 8)? as f64,
                max_lat: read_f32(&data, cursor + 12)? as f64,
            });
            cursor += BBOX_SIZE;
        }

        let mut strings = Vec::with_capacity(string_count);
        cursor = offset_string_offset_table;
        for _ in 0..string_count {
            require_range(&data, cursor, STRING_OFFSET_SIZE)?;
            let str_offset = read_u64(&data, cursor)? as usize;
            let str_length = read_u32(&data, cursor + 8)? as usize;
            require_range(&data, str_offset, str_length)?;
            let value = std::str::from_utf8(&data[str_offset..str_offset + str_length])
                .map_err(|err| PyValueError::new_err(format!("Invalid CGD UTF-8 string: {err}")))?
                .to_owned();
            strings.push(value);
            cursor += STRING_OFFSET_SIZE;
        }

        let mut polygons = Vec::with_capacity(polygon_count);
        let mut rings = Vec::new();
        let mut points = Vec::new();
        for rec in indexes {
            let bbox = *bboxes
                .get(rec.bbox_index)
                .ok_or_else(|| PyValueError::new_err("CGD bbox index out of range"))?;
            let name = strings
                .get(rec.string_index)
                .ok_or_else(|| PyValueError::new_err("CGD string index out of range"))?
                .clone();
            let ring_start = rings.len();
            read_geometry(
                &data,
                rec.geom_offset,
                rec.ring_count,
                &mut rings,
                &mut points,
            )?;
            polygons.push(Polygon {
                bbox,
                ring_start,
                ring_count: rec.ring_count,
                iso2: rec.iso2,
                terminal_code: rec.terminal_code,
                flags: rec.flags,
                name,
            });
        }

        Ok(Self {
            polygons,
            rings,
            points,
        })
    }

    fn lookup_many_indices(&self, lons: &[f64], lats: &[f64]) -> Vec<Option<usize>> {
        lons.iter()
            .zip(lats.iter())
            .map(|(lon, lat)| self.lookup_one(*lon, *lat))
            .collect()
    }

    fn lookup_one(&self, lon: f64, lat: f64) -> Option<usize> {
        if !lon.is_finite()
            || !lat.is_finite()
            || !(-180.0..=180.0).contains(&lon)
            || !(-90.0..=90.0).contains(&lat)
        {
            return None;
        }

        let mut first_hit: Option<usize> = None;
        let mut best_named_ocean: Option<usize> = None;
        let mut best_named_ocean_bbox_area: Option<f64> = None;

        for (idx, polygon) in self.polygons.iter().enumerate() {
            if !polygon.bbox.contains(lon, lat) {
                continue;
            }
            if !self.polygon_covers(lon, lat, polygon) {
                continue;
            }

            if first_hit.is_none() {
                first_hit = Some(idx);
            }

            if polygon.flags & FLAG_COUNTRY != 0 {
                return Some(idx);
            }

            let is_oceanish =
                (polygon.flags & FLAG_OCEAN != 0) || polygon.terminal_code == TERMINAL_OPEN_SEA;
            if !is_oceanish {
                continue;
            }

            let lowered = polygon.name.trim().to_ascii_lowercase();
            if lowered == "ocean" || lowered == "open sea" {
                continue;
            }

            let bbox_area = (polygon.bbox.max_lon - polygon.bbox.min_lon)
                * (polygon.bbox.max_lat - polygon.bbox.min_lat);
            if best_named_ocean.is_none()
                || best_named_ocean_bbox_area.is_none()
                || bbox_area < best_named_ocean_bbox_area.unwrap()
            {
                best_named_ocean = Some(idx);
                best_named_ocean_bbox_area = Some(bbox_area);
            }
        }

        best_named_ocean.or(first_hit)
    }

    fn polygon_covers(&self, lon: f64, lat: f64, polygon: &Polygon) -> bool {
        if polygon.ring_count == 0 {
            return false;
        }

        let outer = self.rings[polygon.ring_start];
        if !self.ring_covers(lon, lat, outer) {
            return false;
        }

        for ring_idx in polygon.ring_start + 1..polygon.ring_start + polygon.ring_count {
            if self.ring_covers(lon, lat, self.rings[ring_idx]) {
                return false;
            }
        }
        true
    }

    fn ring_covers(&self, lon: f64, lat: f64, ring: Ring) -> bool {
        if ring.point_count < 2 {
            return false;
        }

        let mut inside = false;
        let end = ring.point_start + ring.point_count - 1;
        for i in ring.point_start..end {
            let a = self.points[i];
            let b = self.points[i + 1];
            if point_on_segment(lon, lat, a.lon, a.lat, b.lon, b.lat) {
                return true;
            }
            if (a.lat > lat) != (b.lat > lat) {
                let x_at_lat = a.lon + (lat - a.lat) * (b.lon - a.lon) / (b.lat - a.lat);
                if x_at_lat == lon {
                    return true;
                }
                if x_at_lat > lon {
                    inside = !inside;
                }
            }
        }
        inside
    }
}

impl BBox {
    fn contains(&self, lon: f64, lat: f64) -> bool {
        self.min_lon <= lon && lon <= self.max_lon && self.min_lat <= lat && lat <= self.max_lat
    }
}

fn extract_f64_values(obj: &Bound<'_, PyAny>) -> PyResult<Vec<f64>> {
    // Phase 1 uses Python sequence extraction. Keep this in one layer so a
    // buffer-protocol fast path can replace it without touching lookup logic.
    obj.extract::<Vec<f64>>()
}

fn read_geometry(
    data: &[u8],
    offset: usize,
    expected_ring_count: usize,
    rings: &mut Vec<Ring>,
    points: &mut Vec<Point>,
) -> PyResult<()> {
    let mut cursor = offset;
    let ring_count = read_u32(data, cursor)? as usize;
    cursor += 4;
    if ring_count != expected_ring_count {
        return Err(PyValueError::new_err("CGD ring_count mismatch"));
    }

    for _ in 0..ring_count {
        let point_count = read_u32(data, cursor)? as usize;
        cursor += 4;
        let point_start = points.len();
        for _ in 0..point_count {
            let lon = read_f32(data, cursor)? as f64;
            let lat = read_f32(data, cursor + 4)? as f64;
            cursor += 8;
            points.push(Point { lon, lat });
        }
        rings.push(Ring {
            point_start,
            point_count,
        });
    }
    Ok(())
}

fn point_on_segment(px: f64, py: f64, ax: f64, ay: f64, bx: f64, by: f64) -> bool {
    let eps = 1e-12;
    let cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax);
    if cross.abs() > eps {
        return false;
    }
    let dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay);
    if dot < -eps {
        return false;
    }
    let seg_len_sq = (bx - ax).powi(2) + (by - ay).powi(2);
    dot - seg_len_sq <= eps
}

fn decode_iso2(raw: &[u8]) -> Option<String> {
    let cleaned: Vec<u8> = raw.iter().copied().filter(|b| *b != 0).collect();
    if cleaned.is_empty() {
        return None;
    }
    Some(String::from_utf8_lossy(&cleaned).trim().to_owned())
}

fn require_range(data: &[u8], offset: usize, len: usize) -> PyResult<()> {
    match offset.checked_add(len) {
        Some(end) if end <= data.len() => Ok(()),
        _ => Err(PyValueError::new_err("CGD offset out of range")),
    }
}

fn read_u16(data: &[u8], offset: usize) -> PyResult<u16> {
    require_range(data, offset, 2)?;
    Ok(u16::from_le_bytes([data[offset], data[offset + 1]]))
}

fn read_u32(data: &[u8], offset: usize) -> PyResult<u32> {
    require_range(data, offset, 4)?;
    Ok(u32::from_le_bytes([
        data[offset],
        data[offset + 1],
        data[offset + 2],
        data[offset + 3],
    ]))
}

fn read_u64(data: &[u8], offset: usize) -> PyResult<u64> {
    require_range(data, offset, 8)?;
    Ok(u64::from_le_bytes([
        data[offset],
        data[offset + 1],
        data[offset + 2],
        data[offset + 3],
        data[offset + 4],
        data[offset + 5],
        data[offset + 6],
        data[offset + 7],
    ]))
}

fn read_f32(data: &[u8], offset: usize) -> PyResult<f32> {
    require_range(data, offset, 4)?;
    Ok(f32::from_le_bytes([
        data[offset],
        data[offset + 1],
        data[offset + 2],
        data[offset + 3],
    ]))
}

#[pyclass]
struct FfsfRuntimeKernel {
    kernel: FfsfKernel,
}

#[pymethods]
impl FfsfRuntimeKernel {
    #[new]
    fn new(
        py: Python<'_>,
        ffsf_path: &Bound<'_, PyAny>,
        feature_meta_path: &Bound<'_, PyAny>,
    ) -> PyResult<Self> {
        let os = py.import_bound("os")?;
        let ffsf_obj = os.call_method1("fspath", (ffsf_path,))?;
        let meta_obj = os.call_method1("fspath", (feature_meta_path,))?;
        let ffsf_path = PathBuf::from(ffsf_obj.extract::<String>()?);
        let feature_meta_path = PathBuf::from(meta_obj.extract::<String>()?);
        Ok(Self {
            kernel: FfsfKernel::from_files(ffsf_path, feature_meta_path)?,
        })
    }

    #[getter]
    fn backend_name(&self) -> &'static str {
        "native"
    }

    fn query_point_feature_indices(
        &self,
        py: Python<'_>,
        lon: f64,
        lat: f64,
        levels: Vec<i32>,
    ) -> PyResult<PyObject> {
        let hits = self.kernel.query_point_feature_indices(lon, lat, &levels);
        feature_hits_to_py(py, &hits)
    }

    fn query_many_feature_indices(
        &self,
        py: Python<'_>,
        lons: &Bound<'_, PyAny>,
        lats: &Bound<'_, PyAny>,
        levels: Vec<i32>,
    ) -> PyResult<PyObject> {
        let lon_values = extract_f64_values(lons)?;
        let lat_values = extract_f64_values(lats)?;
        if lon_values.len() != lat_values.len() {
            return Err(PyValueError::new_err(
                "lons and lats must have the same length",
            ));
        }

        let out = PyList::empty_bound(py);
        for (lon, lat) in lon_values.into_iter().zip(lat_values.into_iter()) {
            let hits = self.kernel.query_point_feature_indices(lon, lat, &levels);
            out.append(feature_hits_to_py(py, &hits)?)?;
        }
        Ok(out.into_py(py))
    }

    fn country_scope_contains_point(&self, lon: f64, lat: f64, part_indices: Vec<usize>) -> bool {
        self.kernel
            .country_scope_contains_point(lon, lat, &part_indices)
    }

    fn distance_km_to_country_scope(&self, lon: f64, lat: f64, part_indices: Vec<usize>) -> f64 {
        self.kernel
            .distance_km_to_country_scope(lon, lat, &part_indices)
    }

    fn distance_km_to_feature_index(&self, lon: f64, lat: f64, feature_idx: usize) -> f64 {
        self.kernel
            .distance_km_to_feature_index(lon, lat, feature_idx)
    }

    fn query_point_nearest_feature_indices(
        &self,
        py: Python<'_>,
        lon: f64,
        lat: f64,
        max_distance_km: f64,
        levels: Vec<i32>,
        part_feature_indices: Vec<i64>,
    ) -> PyResult<PyObject> {
        let hits = self.kernel.query_point_nearest_feature_indices(
            lon,
            lat,
            max_distance_km,
            &levels,
            &part_feature_indices,
        );
        feature_hits_to_py(py, &hits)
    }
}

fn feature_hits_to_py(py: Python<'_>, hits: &[(i32, usize)]) -> PyResult<PyObject> {
    let dict = PyDict::new_bound(py);
    for (level, feature_idx) in hits {
        dict.set_item(*level, *feature_idx)?;
    }
    Ok(dict.into_py(py))
}

struct FfsfKernel {
    features: Vec<FfsfFeature>,
    part_bboxes: Vec<FfsfBBox>,
    geoms: Vec<FfsfGeom>,
    ring_index: Vec<usize>,
    geometry_data: Vec<u8>,
    feature_levels: Vec<Option<i32>>,
}

#[derive(Clone, Copy)]
struct FfsfFeature {
    part_start_idx: usize,
    part_count: usize,
}

#[derive(Clone, Copy)]
struct FfsfGeom {
    byte_offset: usize,
    byte_len: usize,
    ring_start_idx: usize,
    ring_count: usize,
}

#[derive(Clone, Copy)]
struct FfsfBBox {
    minx: f64,
    miny: f64,
    maxx: f64,
    maxy: f64,
}

impl FfsfKernel {
    fn from_files(ffsf_path: PathBuf, feature_meta_path: PathBuf) -> PyResult<Self> {
        let blob = fs::read(&ffsf_path).map_err(|err| {
            if err.kind() == std::io::ErrorKind::NotFound {
                PyFileNotFoundError::new_err(format!(
                    "FFSF file not found: {}",
                    ffsf_path.display()
                ))
            } else {
                PyValueError::new_err(format!(
                    "Failed to read FFSF file {}: {err}",
                    ffsf_path.display()
                ))
            }
        })?;
        let meta_bytes = fs::read(&feature_meta_path).map_err(|err| {
            if err.kind() == std::io::ErrorKind::NotFound {
                PyFileNotFoundError::new_err(format!(
                    "FFSF feature metadata file not found: {}",
                    feature_meta_path.display()
                ))
            } else {
                PyValueError::new_err(format!(
                    "Failed to read FFSF feature metadata file {}: {err}",
                    feature_meta_path.display()
                ))
            }
        })?;
        Self::from_bytes(blob, &meta_bytes)
    }

    fn from_bytes(blob: Vec<u8>, meta_bytes: &[u8]) -> PyResult<Self> {
        if blob.len() < FFSF_HEADER_SIZE {
            return Err(PyValueError::new_err("Invalid FFSF file (too small)"));
        }
        if &blob[0..4] != b"FFSF" {
            return Err(PyValueError::new_err("Invalid FFSF magic"));
        }
        let version = read_u32(&blob, 4)?;
        if version != 3 {
            return Err(PyValueError::new_err(format!(
                "Unsupported FFSF version {version}; expected v3"
            )));
        }
        let feature_count = read_u32(&blob, 8)? as usize;
        let total_part_count = read_u32(&blob, 12)? as usize;
        let mut offset = FFSF_HEADER_SIZE;

        let mut features = Vec::with_capacity(feature_count);
        for _ in 0..feature_count {
            require_range(&blob, offset, FFSF_FEATURE_INDEX_SIZE)?;
            let part_start_idx = read_u32(&blob, offset + 8)? as usize;
            let part_count = read_u32(&blob, offset + 12)? as usize;
            features.push(FfsfFeature {
                part_start_idx,
                part_count,
            });
            offset += FFSF_FEATURE_INDEX_SIZE;
        }

        let mut part_bboxes = Vec::with_capacity(total_part_count);
        for _ in 0..total_part_count {
            require_range(&blob, offset, FFSF_PART_BBOX_SIZE)?;
            part_bboxes.push(FfsfBBox {
                minx: read_f32(&blob, offset)? as f64,
                miny: read_f32(&blob, offset + 4)? as f64,
                maxx: read_f32(&blob, offset + 8)? as f64,
                maxy: read_f32(&blob, offset + 12)? as f64,
            });
            offset += FFSF_PART_BBOX_SIZE;
        }

        let mut geoms = Vec::with_capacity(total_part_count);
        let mut total_ring_count = 0usize;
        for _ in 0..total_part_count {
            require_range(&blob, offset, FFSF_GEOM_INDEX_SIZE)?;
            let ring_count = read_u32(&blob, offset + 12)? as usize;
            geoms.push(FfsfGeom {
                byte_offset: read_u32(&blob, offset)? as usize,
                byte_len: read_u32(&blob, offset + 4)? as usize,
                ring_start_idx: read_u32(&blob, offset + 8)? as usize,
                ring_count,
            });
            total_ring_count += ring_count;
            offset += FFSF_GEOM_INDEX_SIZE;
        }

        let mut ring_index = Vec::with_capacity(total_ring_count);
        for _ in 0..total_ring_count {
            ring_index.push(read_u32(&blob, offset)? as usize);
            offset += 4;
        }

        require_range(&blob, offset, 0)?;
        let geometry_data = blob[offset..].to_vec();
        let feature_levels = parse_feature_levels(meta_bytes, feature_count)?;

        Ok(Self {
            features,
            part_bboxes,
            geoms,
            ring_index,
            geometry_data,
            feature_levels,
        })
    }

    fn query_point_feature_indices(&self, lon: f64, lat: f64, levels: &[i32]) -> Vec<(i32, usize)> {
        if !lon.is_finite() || !lat.is_finite() {
            return Vec::new();
        }
        let mut hits: Vec<(i32, usize)> = Vec::new();

        for (feature_idx, feature) in self.features.iter().enumerate() {
            let Some(level) = self.feature_levels.get(feature_idx).copied().flatten() else {
                continue;
            };
            if !levels.contains(&level) || hits.iter().any(|(hit_level, _)| *hit_level == level) {
                continue;
            }
            if self.feature_contains_point(*feature, lon, lat) {
                hits.push((level, feature_idx));
            }
            if hits.len() == levels.len() {
                break;
            }
        }

        hits
    }

    fn query_point_nearest_feature_indices(
        &self,
        lon: f64,
        lat: f64,
        max_distance_km: f64,
        levels: &[i32],
        part_feature_indices: &[i64],
    ) -> Vec<(i32, usize)> {
        if !lon.is_finite() || !lat.is_finite() || max_distance_km <= 0.0 {
            return Vec::new();
        }

        let threshold_deg = max_distance_km / 111.0;
        let qminx = lon - threshold_deg;
        let qmaxx = lon + threshold_deg;
        let qminy = lat - threshold_deg;
        let qmaxy = lat + threshold_deg;
        let mut nearest_by_level: Vec<(i32, f64, usize)> = Vec::new();

        for (part_idx, bbox) in self.part_bboxes.iter().copied().enumerate() {
            if bbox.maxx < qminx || bbox.minx > qmaxx || bbox.maxy < qminy || bbox.miny > qmaxy {
                continue;
            }

            let Some(raw_feature_idx) = part_feature_indices.get(part_idx).copied() else {
                continue;
            };
            if raw_feature_idx < 0 {
                continue;
            }
            let feature_idx = raw_feature_idx as usize;
            let Some(level) = self.feature_levels.get(feature_idx).copied().flatten() else {
                continue;
            };
            if !levels.contains(&level) {
                continue;
            }

            let dist_km = self.distance_km_to_part(lon, lat, part_idx);
            if dist_km > max_distance_km {
                continue;
            }

            if let Some(best) = nearest_by_level
                .iter_mut()
                .find(|(best_level, _, _)| *best_level == level)
            {
                if dist_km < best.1 {
                    *best = (level, dist_km, feature_idx);
                }
            } else {
                nearest_by_level.push((level, dist_km, feature_idx));
            }
        }

        nearest_by_level
            .into_iter()
            .map(|(level, _, feature_idx)| (level, feature_idx))
            .collect()
    }

    fn country_scope_contains_point(&self, lon: f64, lat: f64, part_indices: &[usize]) -> bool {
        if !lon.is_finite() || !lat.is_finite() {
            return false;
        }
        part_indices
            .iter()
            .any(|part_idx| self.part_contains_point(*part_idx, lon, lat))
    }

    fn distance_km_to_country_scope(&self, lon: f64, lat: f64, part_indices: &[usize]) -> f64 {
        if part_indices.is_empty() || !lon.is_finite() || !lat.is_finite() {
            return f64::INFINITY;
        }
        if self.country_scope_contains_point(lon, lat, part_indices) {
            return 0.0;
        }

        let mut min_dist = f64::INFINITY;
        for part_idx in part_indices {
            let dist = self.distance_km_to_part(lon, lat, *part_idx);
            if dist < min_dist {
                min_dist = dist;
            }
        }
        min_dist
    }

    fn distance_km_to_feature_index(&self, lon: f64, lat: f64, feature_idx: usize) -> f64 {
        if !lon.is_finite() || !lat.is_finite() {
            return f64::INFINITY;
        }
        let Some(feature) = self.features.get(feature_idx).copied() else {
            return f64::INFINITY;
        };
        let mut min_dist = f64::INFINITY;
        for part_idx in feature.part_start_idx..feature.part_start_idx + feature.part_count {
            let dist = self.distance_km_to_part(lon, lat, part_idx);
            if dist < min_dist {
                min_dist = dist;
            }
        }
        min_dist
    }

    fn feature_contains_point(&self, feature: FfsfFeature, lon: f64, lat: f64) -> bool {
        for part_idx in feature.part_start_idx..feature.part_start_idx + feature.part_count {
            if self.part_contains_point(part_idx, lon, lat) {
                return true;
            }
        }
        false
    }

    fn part_contains_point(&self, part_idx: usize, lon: f64, lat: f64) -> bool {
        let Some(bbox) = self.part_bboxes.get(part_idx).copied() else {
            return false;
        };
        if !(bbox.minx <= lon && lon <= bbox.maxx && bbox.miny <= lat && lat <= bbox.maxy) {
            return false;
        }

        let Some(geom) = self.geoms.get(part_idx).copied() else {
            return false;
        };
        if geom.ring_count == 0 {
            return false;
        }

        let spanx = bbox.maxx - bbox.minx;
        let spany = bbox.maxy - bbox.miny;
        let qx = quantize_ffsf(lon, bbox.minx, spanx);
        let qy = quantize_ffsf(lat, bbox.miny, spany);

        let mut cursor = geom.byte_offset;
        let end = match geom.byte_offset.checked_add(geom.byte_len) {
            Some(value) => value,
            None => return false,
        };
        if end > self.geometry_data.len() {
            return false;
        }

        let mut outer_match = false;
        for ring_ord in 0..geom.ring_count {
            let ring_idx = geom.ring_start_idx + ring_ord;
            let Some(point_count) = self.ring_index.get(ring_idx).copied() else {
                return false;
            };
            let byte_count = match point_count.checked_mul(4) {
                Some(value) => value,
                None => return false,
            };
            let ring_end = match cursor.checked_add(byte_count) {
                Some(value) => value,
                None => return false,
            };
            if ring_end > end {
                return false;
            }
            let contains = point_in_ffsf_ring(qx, qy, &self.geometry_data[cursor..ring_end]);
            cursor = ring_end;

            if ring_ord == 0 {
                if !contains {
                    return false;
                }
                outer_match = true;
            } else if contains {
                return false;
            }
        }

        outer_match
    }

    fn distance_km_to_part(&self, lon: f64, lat: f64, part_idx: usize) -> f64 {
        let Some(bbox) = self.part_bboxes.get(part_idx).copied() else {
            return f64::INFINITY;
        };
        let Some(geom) = self.geoms.get(part_idx).copied() else {
            return f64::INFINITY;
        };
        if geom.ring_count == 0 {
            return f64::INFINITY;
        }

        let spanx = bbox.maxx - bbox.minx;
        let spany = bbox.maxy - bbox.miny;
        let mut cursor = geom.byte_offset;
        let end = match geom.byte_offset.checked_add(geom.byte_len) {
            Some(value) => value,
            None => return f64::INFINITY,
        };
        if end > self.geometry_data.len() {
            return f64::INFINITY;
        }

        let mut min_dist = f64::INFINITY;
        for ring_ord in 0..geom.ring_count {
            let ring_idx = geom.ring_start_idx + ring_ord;
            let Some(point_count) = self.ring_index.get(ring_idx).copied() else {
                return f64::INFINITY;
            };
            let byte_count = match point_count.checked_mul(4) {
                Some(value) => value,
                None => return f64::INFINITY,
            };
            let ring_end = match cursor.checked_add(byte_count) {
                Some(value) => value,
                None => return f64::INFINITY,
            };
            if ring_end > end {
                return f64::INFINITY;
            }

            let dist = distance_km_to_ffsf_ring(
                lon,
                lat,
                &self.geometry_data[cursor..ring_end],
                bbox.minx,
                bbox.miny,
                spanx,
                spany,
            );
            if dist < min_dist {
                min_dist = dist;
            }
            cursor = ring_end;
        }
        min_dist
    }
}

fn parse_feature_levels(meta_bytes: &[u8], expected_len: usize) -> PyResult<Vec<Option<i32>>> {
    let raw: Value = serde_json::from_slice(meta_bytes).map_err(|err| {
        PyValueError::new_err(format!("Invalid FFSF feature metadata JSON: {err}"))
    })?;
    let Some(items) = raw.as_array() else {
        return Err(PyValueError::new_err(
            "feature_meta_by_index dataset must be a JSON list",
        ));
    };
    if items.len() != expected_len {
        return Err(PyValueError::new_err(
            "feature_meta_by_index length must match FFSF FeatureCount",
        ));
    }
    Ok(items
        .iter()
        .map(|item| {
            item.get("level")
                .and_then(|level| level.as_i64())
                .and_then(|level| i32::try_from(level).ok())
        })
        .collect())
}

fn quantize_ffsf(value: f64, min_value: f64, span: f64) -> u16 {
    if span == 0.0 {
        return 0;
    }
    let scaled = (value - min_value) / span * 65535.0;
    if scaled <= 0.0 {
        return 0;
    }
    if scaled >= 65535.0 {
        return 65535;
    }
    (scaled + 0.5).floor() as u16
}

fn point_in_ffsf_ring(qx: u16, qy: u16, ring_data: &[u8]) -> bool {
    if ring_data.len() < 12 || ring_data.len() % 4 != 0 {
        return false;
    }
    let point_count = ring_data.len() / 4;
    let mut inside = false;
    let mut j = point_count - 1;
    for i in 0..point_count {
        let xi = read_u16_from_slice(ring_data, i * 4);
        let yi = read_u16_from_slice(ring_data, i * 4 + 2);
        let xj = read_u16_from_slice(ring_data, j * 4);
        let yj = read_u16_from_slice(ring_data, j * 4 + 2);

        if point_on_ffsf_segment(qx, qy, xj, yj, xi, yi) {
            return true;
        }

        let intersects = (yi > qy) != (yj > qy);
        if intersects {
            let den = i32::from(yj) - i32::from(yi);
            if den != 0 {
                let x_cross = f64::from(i32::from(xj) - i32::from(xi))
                    * f64::from(i32::from(qy) - i32::from(yi))
                    / f64::from(den)
                    + f64::from(xi);
                if f64::from(qx) < x_cross {
                    inside = !inside;
                }
            }
        }
        j = i;
    }
    inside
}

fn point_on_ffsf_segment(px: u16, py: u16, x1: u16, y1: u16, x2: u16, y2: u16) -> bool {
    if px < x1.min(x2) || px > x1.max(x2) || py < y1.min(y2) || py > y1.max(y2) {
        return false;
    }
    (i64::from(x2) - i64::from(x1)) * (i64::from(py) - i64::from(y1))
        == (i64::from(y2) - i64::from(y1)) * (i64::from(px) - i64::from(x1))
}

fn distance_km_to_ffsf_ring(
    lon: f64,
    lat: f64,
    ring_data: &[u8],
    minx: f64,
    miny: f64,
    mut spanx: f64,
    mut spany: f64,
) -> f64 {
    if ring_data.len() < 8 || ring_data.len() % 4 != 0 {
        return f64::INFINITY;
    }
    if spanx == 0.0 {
        spanx = 1.0;
    }
    if spany == 0.0 {
        spany = 1.0;
    }

    let point_count = ring_data.len() / 4;
    if point_count < 2 {
        return f64::INFINITY;
    }

    let first = decode_ffsf_point(ring_data, 0, minx, miny, spanx, spany);
    let last = decode_ffsf_point(ring_data, point_count - 1, minx, miny, spanx, spany);
    let closed = first == last;
    let limit = if closed { point_count - 1 } else { point_count };
    let mut min_dist = f64::INFINITY;

    for idx in 0..limit {
        let (x1, y1) = decode_ffsf_point(ring_data, idx, minx, miny, spanx, spany);
        let (x2, y2) =
            decode_ffsf_point(ring_data, (idx + 1) % point_count, minx, miny, spanx, spany);
        let (nx, ny) = nearest_point_on_segment(lon, lat, x1, y1, x2, y2);
        let dist = haversine_km(lat, lon, ny, nx);
        if dist < min_dist {
            min_dist = dist;
        }
    }

    min_dist
}

fn decode_ffsf_point(
    ring_data: &[u8],
    point_idx: usize,
    minx: f64,
    miny: f64,
    spanx: f64,
    spany: f64,
) -> (f64, f64) {
    let offset = point_idx * 4;
    let qx = f64::from(read_u16_from_slice(ring_data, offset));
    let qy = f64::from(read_u16_from_slice(ring_data, offset + 2));
    let x = minx + (qx / 65535.0) * spanx;
    let y = miny + (qy / 65535.0) * spany;
    (x, y)
}

fn nearest_point_on_segment(px: f64, py: f64, x1: f64, y1: f64, x2: f64, y2: f64) -> (f64, f64) {
    let dx = x2 - x1;
    let dy = y2 - y1;
    if dx == 0.0 && dy == 0.0 {
        return (x1, y1);
    }

    let t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy);
    if t <= 0.0 {
        return (x1, y1);
    }
    if t >= 1.0 {
        return (x2, y2);
    }
    (x1 + t * dx, y1 + t * dy)
}

fn haversine_km(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    let r = 6371.0;
    let lat1_r = lat1.to_radians();
    let lon1_r = lon1.to_radians();
    let lat2_r = lat2.to_radians();
    let lon2_r = lon2.to_radians();

    let dlat = lat2_r - lat1_r;
    let dlon = lon2_r - lon1_r;
    let a = (dlat / 2.0).sin().powi(2) + lat1_r.cos() * lat2_r.cos() * (dlon / 2.0).sin().powi(2);
    let c = 2.0 * a.sqrt().asin();
    r * c
}

fn read_u16_from_slice(data: &[u8], offset: usize) -> u16 {
    u16::from_le_bytes([data[offset], data[offset + 1]])
}
