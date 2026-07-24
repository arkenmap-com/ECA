#!/usr/bin/env python3
"""Create mutually exclusive 12-hour fire-growth bands from Cell2Fire grids."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
import rasterio


ROOT = Path(__file__).resolve().parent
HOURS = (12, 24, 36, 48)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name",
        default="aoi-25m-bcdem-summer-p90-48h-prevailing-single-center",
        help="Run folder and scratch scenario name.",
    )
    parser.add_argument("--cell-size", type=float, default=25.0)
    parser.add_argument("--results-dirname", default="results-growth")
    parser.add_argument("--fuel-name", default=None)
    args = parser.parse_args()
    run = ROOT / "runs" / args.name
    grids = Path(f"/private/tmp/fire-sim/{args.name}/{args.results_dirname}/run_0001/Grids/Grids1")
    output_dir = run / "outputs"
    fuel_name = args.fuel_name or f"fuel_{int(args.cell_size)}m.tif"
    template = run / "data" / "derived" / fuel_name

    cumulative = {}
    for hour in HOURS:
        path = grids / f"ForestGrid{hour:02d}.csv"
        if not path.exists():
            raise SystemExit(f"Missing intermediate fire grid: {path}")
        cumulative[hour] = np.loadtxt(path, delimiter=",") == 1

    shape = cumulative[HOURS[0]].shape
    if any(values.shape != shape for values in cumulative.values()):
        raise SystemExit("Intermediate fire grids do not have matching shapes.")

    intervals = np.zeros(shape, dtype=np.uint8)
    previous = np.zeros(shape, dtype=bool)
    summary_rows = []
    for class_value, hour in enumerate(HOURS, start=1):
        current = cumulative[hour]
        new = current & ~previous
        intervals[new] = class_value
        summary_rows.append({
            "interval": f"{hour - 12}-{hour} hours",
            "class_value": class_value,
            "new_cells": int(new.sum()),
            "new_area_km2": float(new.sum() * args.cell_size**2 / 1_000_000),
            "cumulative_cells": int(current.sum()),
            "cumulative_area_km2": float(current.sum() * args.cell_size**2 / 1_000_000),
        })
        previous = current

    output_dir.mkdir(parents=True, exist_ok=True)
    tif = output_dir / "fire_growth_12h_intervals.tif"
    with rasterio.open(template) as source:
        profile = source.profile.copy()
    profile.update(dtype="uint8", nodata=0, count=1, compress="deflate", tiled=True)
    with rasterio.open(tif, "w", **profile) as target:
        target.write(intervals, 1)

    colors = output_dir / "fire_growth_12h_colors.txt"
    colors.write_text(
        "0 0 0 0 0\n"
        "1 255 237 160 230\n"
        "2 254 178 76 235\n"
        "3 240 59 32 240\n"
        "4 128 0 38 245\n",
        encoding="utf-8",
    )
    png = output_dir / "fire_growth_12h_intervals.png"
    subprocess.run([
        "gdaldem", "color-relief", "-alpha", "-exact_color_entry",
        str(tif), str(colors), str(png),
    ], check=True)
    summary = {
        "source_grids": [f"ForestGrid{hour:02d}.csv" for hour in HOURS],
        "classification": "first 12-hour interval in which each cell is burned",
        "cell_size_m": args.cell_size,
        "intervals": summary_rows,
    }
    (output_dir / "fire_growth_12h_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
