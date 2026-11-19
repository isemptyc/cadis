"""Regenerate the bundled centerline-derived rivers with a 10 m buffer.

Run from the Cadis checkout with the sibling project's curated waterbody
builder, local OSM PBFs, osmium, shapely and pyproj available:

    python scripts/regenerate_river_waterbody.py --work-dir /tmp/cadis-rivers

The candidate is written under the work directory for verification. Existing
mapped water polygons (including Tagus), lakes and seas retain their exact
FFSF geometry and feature order.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from math import floor
from pathlib import Path

from pyproj import Transformer, datadir
from shapely.geometry import LineString, MultiPolygon, mapping
from shapely.ops import transform, unary_union

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO.parent / "scripts"))
sys.path.insert(0, str(REPO))
from build_waterbody_dataset_curated import (
    FFSFv3Builder,
    RESOLVED_JSON,
    _collect_stem_ways,
    _pbf_candidates,
)
from cadis.waterbody.waterbody_index import WaterbodyIndex

BUFFER_METRES = 10
SIMPLIFICATION_METRES = 0.5
TILE_DEGREES = 0.1


def extract_pbf(pbf: Path, ids: list[str], output: Path) -> None:
    if output.exists() and output.stat().st_size > 100:
        return
    partial = output.with_suffix(".partial.osm")
    result = subprocess.run(
        ["osmium", "getid", str(pbf), *ids, "-r", "--no-progress", "-o", str(partial), "-O"],
        capture_output=True, text=True,
    )
    # A partial cross-border relation is expected in individual extracts.
    if result.returncode > 1 or not partial.exists():
        raise RuntimeError(f"{pbf.name}: {result.stderr}")
    partial.replace(output)
    print(f"Extracted {pbf.name}", flush=True)


def load_stems(extracts: dict[Path, list[str]]) -> dict[str, set[tuple]]:
    stem_ids = defaultdict(set)
    for path, relations in extracts.items():
        for relation in relations:
            collected = _collect_stem_ways(path, relation)
            if collected:
                stem_ids[relation].update(collected[0])

    stems = defaultdict(set)
    for path, relations in extracts.items():
        root = ET.parse(path).getroot()
        nodes = {
            node.get("id"): (float(node.get("lon")), float(node.get("lat")))
            for node in root.findall("node")
        }
        by_way = defaultdict(list)
        for relation in relations:
            for way_id in stem_ids[relation]:
                by_way[way_id].append(relation)
        for way in root.findall("way"):
            owners = by_way.get(way.get("id"))
            if not owners:
                continue
            coords = []
            for ref in way.findall("nd"):
                point = nodes.get(ref.get("ref"))
                if point is None:
                    if len(coords) >= 2:
                        for relation in owners:
                            stems[relation].add(tuple(coords))
                    coords = []
                else:
                    coords.append(point)
            if len(coords) >= 2:
                for relation in owners:
                    stems[relation].add(tuple(coords))
    return stems


def river_geometry(stems: set[tuple]) -> MultiPolygon:
    groups = defaultdict(list)
    for coords in sorted(stems):
        chunk = [coords[0]]
        for point in coords[1:]:
            chunk.append(point)
            # Preserve the shared endpoint so adjacent corridors overlap.
            if max(abs(point[0] - chunk[0][0]), abs(point[1] - chunk[0][1])) >= TILE_DEGREES:
                key = (floor(chunk[0][0] / TILE_DEGREES), floor(chunk[0][1] / TILE_DEGREES))
                groups[key].append(LineString(chunk))
                chunk = [point]
        if len(chunk) >= 2:
            key = (floor(chunk[0][0] / TILE_DEGREES), floor(chunk[0][1] / TILE_DEGREES))
            groups[key].append(LineString(chunk))

    polygons = []
    for (x, y), lines in sorted(groups.items()):
        lon, lat = (x + 0.5) * TILE_DEGREES, (y + 0.5) * TILE_DEGREES
        local = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m"
        forward = Transformer.from_crs("EPSG:4326", local, always_xy=True).transform
        inverse = Transformer.from_crs(local, "EPSG:4326", always_xy=True).transform
        water = transform(forward, unary_union(lines)).buffer(BUFFER_METRES, quad_segs=4)
        water = water.simplify(SIMPLIFICATION_METRES, preserve_topology=True)
        for polygon in getattr(water, "geoms", [water]):
            if polygon.geom_type == "Polygon" and not polygon.is_empty:
                polygons.append(transform(inverse, polygon))
    return MultiPolygon(polygons)


def compact_builder(builder: FFSFv3Builder) -> FFSFv3Builder:
    """Remove replaced parts without decoding any unchanged geometry."""
    compact = FFSFv3Builder()
    for entry, meta in zip(builder._feature_entries, builder._meta):
        _, _, start, count = entry
        new_start = compact._part_cursor
        for part in range(start, start + count):
            offset, length, ring_start, ring_count = builder._geom_entries[part]
            compact._part_bboxes.append(builder._part_bboxes[part])
            compact._geom_entries.append(
                (len(compact._geometry_data), length, len(compact._ring_index), ring_count)
            )
            compact._ring_index.extend(builder._ring_index[ring_start:ring_start + ring_count])
            compact._geometry_data.extend(builder._geometry_data[offset:offset + length])
            compact._part_cursor += 1
        compact._feature_entries.append((0, 0, new_start, count))
        compact._meta.append(meta)
    return compact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--proj-data", type=Path, help="Override the PROJ database directory")
    args = parser.parse_args()
    if args.proj_data:
        datadir.set_data_dir(str(args.proj_data))
    work = args.work_dir.resolve()
    extract_dir = work / "extracts"
    extract_dir.mkdir(parents=True, exist_ok=True)
    base = REPO / "cadis/waterbody/data"
    builder = FFSFv3Builder()
    builder.load_existing(base / "waterbody.ffsf", base / "waterbody_meta.json")
    active = {
        meta["feature_id"].removeprefix("curated_"): i
        for i, meta in enumerate(builder._meta)
        if meta["type"] == "river" and meta["feature_id"].startswith("curated_")
    }
    entries = {
        row["osm"]: row
        for row in json.loads(RESOLVED_JSON.read_text())["rivers"]
        if row["osm"] in active
    }
    if set(entries) != set(active):
        raise RuntimeError("Missing curated river source entries")
    jobs = defaultdict(list)
    for relation, row in entries.items():
        for pbf in _pbf_candidates(row["countries"]):
            jobs[pbf].append(relation)
    extracts = {extract_dir / (pbf.stem + ".osm"): ids for pbf, ids in jobs.items()}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(extract_pbf, pbf, ids, extract_dir / (pbf.stem + ".osm"))
            for pbf, ids in sorted(jobs.items(), key=lambda item: -item[0].stat().st_size)
        ]
        for future in futures:
            future.result()
    stems = load_stems(extracts)
    for relation, index in active.items():
        if not stems[relation]:
            raise RuntimeError(f"No source centerline for {relation}")
        meta = builder._meta[index]
        geometry = river_geometry(stems[relation])
        if geometry.is_empty:
            raise RuntimeError(f"Empty regenerated geometry for {relation}")
        builder.add_feature(
            meta["feature_id"], meta["name"], meta["names"], meta["native"], meta["type"],
            mapping(geometry),
        )
        builder._feature_entries[index] = builder._feature_entries.pop()
        builder._meta[index] = builder._meta.pop()
        print(f"{meta['name']}: {len(geometry.geoms)} parts", flush=True)

    out = work / "candidate"
    compact_builder(builder).write(out, "waterbody.ffsf", "waterbody_meta.json")
    candidate = WaterbodyIndex(out)
    for relation, index in active.items():
        lines = [LineString(points) for points in sorted(stems[relation])]
        rng = random.Random(42)
        probes = [
            line.interpolate(rng.random(), normalized=True)
            for line in rng.choices(lines, weights=[line.length for line in lines], k=500)
        ]
        feature = candidate._features[index]
        matched = sum(
            any(candidate._part_contains(i, point.x, point.y)
                for i in range(feature.part_start, feature.part_start + feature.part_count))
            for point in probes
        )
        print(f"{candidate._meta[index]['name']}: {matched}/500 sampled centerline points", flush=True)
        if matched != 500:
            raise RuntimeError(f"Centerline regression for {relation}")


if __name__ == "__main__":
    main()
