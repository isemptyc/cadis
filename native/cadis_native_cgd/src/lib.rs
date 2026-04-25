use pyo3::exceptions::{PyFileNotFoundError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
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
                PyValueError::new_err(format!("Failed to read CGD file {}: {err}", cgd_path.display()))
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
            return Err(PyValueError::new_err("lons and lats must have the same length"));
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
            read_geometry(&data, rec.geom_offset, rec.ring_count, &mut rings, &mut points)?;
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

            let bbox_area =
                (polygon.bbox.max_lon - polygon.bbox.min_lon) * (polygon.bbox.max_lat - polygon.bbox.min_lat);
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
