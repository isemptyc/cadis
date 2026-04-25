from __future__ import annotations

import argparse
import math
from pathlib import Path

from cadis.world.cgd_binary import CGDReader
from cadis_native_cgd import CgdWorldKernel


POINTS = [
    ("tokyo", 139.76, 35.68),
    ("taipei", 121.56, 25.03),
    ("sea-of-japan", 135.47042885544565, 39.48432435620471),
    ("open-sea", -150.0, 0.0),
    ("antarctica", 0.0, -82.0),
    ("north-pole-out-of-range", 0.0, 91.0),
    ("nan", math.nan, 0.0),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cgd",
        type=Path,
        default=Path("cadis/world/data/ne.global.v0.1.0.cgd"),
        help="Path to the CGD file to compare.",
    )
    args = parser.parse_args()

    python_reader = CGDReader(args.cgd)
    native_kernel = CgdWorldKernel(args.cgd)

    failures = 0
    lons = [lon for _name, lon, _lat in POINTS]
    lats = [lat for _name, _lon, lat in POINTS]
    native_batch = native_kernel.lookup_many_lons_lats(lons, lats)

    for index, (name, lon, lat) in enumerate(POINTS):
        expected = python_reader.lookup(lon, lat)
        single = native_kernel.lookup(lon, lat)
        batch = native_batch[index]
        if expected != single or expected != batch:
            failures += 1
            print(f"FAIL {name}")
            print(f"  python: {expected}")
            print(f"  native single: {single}")
            print(f"  native batch:  {batch}")

    if failures:
        print(f"{failures} parity failure(s)")
        return 1

    print(f"{len(POINTS)} parity cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
