#!/usr/bin/env python3
"""Compare Cadis lookup() and lookup_many() against an EONA runtime DB."""

from __future__ import annotations

import argparse
import json
import random
import resource
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cadis
from cadis import _api as cadis_api


DEFAULT_DB = Path("/Users/isempty/EONA/eona-backend/workspace/users/eona/db/runtime.db")


def _canonical(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load_rows(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return [
            {
                "id": str(row["photo_id"]),
                "lat": float(row["raw_latitude"]),
                "lon": float(row["raw_longitude"]),
                "persisted_iso2": row["iso2"],
                "persisted_class": row["class"],
            }
            for row in connection.execute(
                """
                SELECT
                    photo_id,
                    raw_latitude,
                    raw_longitude,
                    json_extract(cadis_result_json, '$.state.world.iso2') AS iso2,
                    json_extract(cadis_result_json, '$.state.world.classification') AS class
                FROM photo
                WHERE raw_latitude IS NOT NULL AND raw_longitude IS NOT NULL
                ORDER BY photo_id ASC
                """
            )
        ]


def _select_rows(rows: list[dict[str, Any]], *, sample_size: int | None, seed: int) -> list[dict[str, Any]]:
    if sample_size is None or sample_size >= len(rows):
        return rows
    rng = random.Random(seed)
    indexes = sorted(rng.sample(range(len(rows)), sample_size))
    return [rows[index] for index in indexes]


def _compare_lookup_many(*, rows: list[dict[str, Any]], batch_size: int, seed: int) -> dict[str, Any]:
    points = [{"id": row["id"], "lat": row["lat"], "lon": row["lon"]} for row in rows]
    single_by_id: dict[str, str] = {}
    single_status: Counter[tuple[object, object, object, object]] = Counter()

    single_start = time.perf_counter()
    for point in points:
        payload = cadis.lookup(point["lat"], point["lon"])
        single_by_id[str(point["id"])] = _canonical(payload)
        execution = payload.get("execution") if isinstance(payload, dict) else {}
        state = payload.get("state") if isinstance(payload, dict) else {}
        world = state.get("world") if isinstance(state, dict) else {}
        single_status[
            (
                execution.get("lookup_status") if isinstance(execution, dict) else None,
                execution.get("resolution_state") if isinstance(execution, dict) else None,
                world.get("classification") if isinstance(world, dict) else None,
                world.get("iso2") if isinstance(world, dict) else None,
            )
        ] += 1
    single_elapsed = time.perf_counter() - single_start

    batch_start = time.perf_counter()
    batch_report = cadis_api._lookup_many_with_diagnostics(points)
    batch_all = batch_report["results"]
    batch_elapsed = time.perf_counter() - batch_start

    compare_start = time.perf_counter()
    batch_mismatches = []
    for item in batch_all:
        if _canonical(item.get("lookup")) != single_by_id.get(str(item.get("id"))):
            batch_mismatches.append(str(item.get("id")))
            if len(batch_mismatches) >= 10:
                break
    batch_compare_elapsed = time.perf_counter() - compare_start

    chunk_start = time.perf_counter()
    chunked = []
    for offset in range(0, len(points), batch_size):
        chunked.extend(cadis.lookup_many(points[offset : offset + batch_size]))
    chunk_elapsed = time.perf_counter() - chunk_start

    chunk_compare_start = time.perf_counter()
    chunk_mismatches = []
    for all_item, chunk_item in zip(batch_all, chunked, strict=True):
        if all_item["id"] != chunk_item["id"] or _canonical(all_item["lookup"]) != _canonical(chunk_item["lookup"]):
            chunk_mismatches.append(str(all_item.get("id")))
            if len(chunk_mismatches) >= 10:
                break
    chunk_compare_elapsed = time.perf_counter() - chunk_compare_start

    shuffled = list(points)
    random.Random(seed).shuffle(shuffled)
    shuffle_start = time.perf_counter()
    shuffled_out = cadis.lookup_many(shuffled)
    shuffle_elapsed = time.perf_counter() - shuffle_start
    shuffle_compare_start = time.perf_counter()
    shuffled_by_id = {str(item["id"]): _canonical(item["lookup"]) for item in shuffled_out}
    shuffle_mismatches = [
        str(point["id"])
        for point in points
        if shuffled_by_id[str(point["id"])] != single_by_id[str(point["id"])]
    ][:10]
    shuffle_compare_elapsed = time.perf_counter() - shuffle_compare_start

    return {
        "cadis_version": cadis.__version__,
        "rows": len(points),
        "batch_size": batch_size,
        "single_elapsed_sec": round(single_elapsed, 3),
        "batch_all_elapsed_sec": round(batch_elapsed, 3),
        "batch_compare_elapsed_sec": round(batch_compare_elapsed, 3),
        "chunked_elapsed_sec": round(chunk_elapsed, 3),
        "chunked_compare_elapsed_sec": round(chunk_compare_elapsed, 3),
        "shuffled_elapsed_sec": round(shuffle_elapsed, 3),
        "shuffled_compare_elapsed_sec": round(shuffle_compare_elapsed, 3),
        "batch_planner_diagnostics": batch_report["diagnostics"],
        "maxrss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "batch_all_vs_single_mismatch_ids": batch_mismatches,
        "chunked_vs_all_mismatch_ids": chunk_mismatches,
        "shuffled_vs_single_mismatch_ids": shuffle_mismatches,
        "status_distribution_top20": [
            {"status": list(key), "count": count}
            for key, count in single_status.most_common(20)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--sample-size", type=int, default=3000)
    parser.add_argument("--all", action="store_true", help="Use every GPS row in the DB.")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260424)
    args = parser.parse_args()

    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")
    if not args.db.exists():
        raise SystemExit(f"DB not found: {args.db}")

    all_rows = _load_rows(args.db)
    sample_size = None if args.all else max(1, int(args.sample_size))
    rows = _select_rows(all_rows, sample_size=sample_size, seed=args.seed)
    persisted_distribution = Counter((row["persisted_class"], row["persisted_iso2"]) for row in rows)
    result = _compare_lookup_many(rows=rows, batch_size=args.batch_size, seed=args.seed)
    result["gps_rows_total"] = len(all_rows)
    result["persisted_distribution_top20"] = [
        {"persisted": list(key), "count": count}
        for key, count in persisted_distribution.most_common(20)
    ]
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))

    if (
        result["batch_all_vs_single_mismatch_ids"]
        or result["chunked_vs_all_mismatch_ids"]
        or result["shuffled_vs_single_mismatch_ids"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
