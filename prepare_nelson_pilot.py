#!/usr/bin/env python3
"""Build Cell2Fire inputs for the Nelson, BC exploratory pilot."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "nelson-pilot" / "raw"
DERIVED = ROOT / "nelson-pilot" / "derived"
OUT = ROOT / "Cell2Fire" / "data" / "nelson-pilot"

# CWFIS FBP Fuel Types 2024 values observed in this Nelson subset. Values 101
# and 102 are non-burnable. Mixedwood codes retain their conifer percentage.
FUEL_MAP = {
    2: ("C2", ""), 3: ("C3", ""), 4: ("C4", ""), 5: ("C5", ""),
    13: ("D1", ""), 31: ("O1a", ""), 101: ("NF", ""), 102: ("NF", ""),
    415: ("M1", "15"), 625: ("M1", "25"), 650: ("M1", "50"),
    675: ("M1", "75"),
}


def xyz_values(path: Path, rows: int, cols: int) -> np.ndarray:
    values = np.loadtxt(path, usecols=2)
    return values.reshape(rows, cols)


def main() -> None:
    info = json.loads(subprocess.check_output([
        "gdalinfo", "-json", str(RAW / "fuel_100m.tif")
    ], text=True))
    cols, rows = info["size"]
    origin_x, cell_x, _, origin_y, _, cell_y = info["geoTransform"]

    fuel = xyz_values(Path("/private/tmp/nelson-fuel.xyz"), rows, cols).astype(int)
    elev = xyz_values(DERIVED / "elevation_250m.xyz", rows, cols)
    slope = xyz_values(DERIVED / "slope_percent.xyz", rows, cols)
    aspect = xyz_values(DERIVED / "aspect_degrees.xyz", rows, cols)

    missing = sorted(set(np.unique(fuel)) - set(FUEL_MAP))
    if missing:
        raise ValueError(f"Unmapped CWFIS fuel values: {missing}")

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "Forest.asc").open("w", encoding="utf-8") as f:
        f.write(f"ncols {cols}\n")
        f.write(f"nrows {rows}\n")
        f.write(f"xllcorner {origin_x}\n")
        f.write(f"yllcorner {origin_y + rows * cell_y}\n")
        f.write(f"cellsize {abs(cell_x)}\n")
        f.write("NODATA_value -9999\n")
        for row in fuel:
            f.write(" ".join(map(str, row)) + "\n")

    columns = [
        "fueltype", "mon", "jd", "M", "jd_min", "lat", "lon", "elev",
        "ffmc", "ws", "waz", "bui", "ps", "saz", "pc", "pdf", "gfl",
        "cur", "time", "pattern",
    ]
    with (OUT / "Data.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for raw_fuel, z, slp, asp in zip(
            fuel.ravel(), elev.ravel(), slope.ravel(), aspect.ravel(), strict=True
        ):
            fuel_type, percent_conifer = FUEL_MAP[int(raw_fuel)]
            writer.writerow({
                "fueltype": fuel_type, "lat": "49.50", "lon": "-117.28",
                "elev": f"{z:.1f}", "ps": f"{max(slp, 0):.2f}",
                "saz": f"{0 if asp < 0 else asp:.1f}", "pc": percent_conifer,
                "gfl": "0.75", "time": "20",
            })

    # Select a burnable cell nearest a point north-west of Nelson for a single,
    # deterministic ignition. IDs are one-based and follow raster row-major order.
    target_row, target_col = 55, 95
    candidates = np.argwhere(np.isin(fuel, [2, 3, 4, 5, 13, 31, 415, 625, 650, 675]))
    row, col = min(candidates, key=lambda rc: (rc[0] - target_row) ** 2 + (rc[1] - target_col) ** 2)
    cell_id = int(row * cols + col + 1)
    with (OUT / "Ignitions.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Year", "Ncell"])
        writer.writerow([1, cell_id])

    weather = [
        ["NELSON_TEST", "2026-08-15 13:00", 0, 25, 25, 20, 240, 90, 70, 400, 12, 90, 30],
        ["NELSON_TEST", "2026-08-15 14:00", 0, 26, 23, 22, 240, 91, 72, 400, 15, 92, 35],
        ["NELSON_TEST", "2026-08-15 15:00", 0, 27, 21, 24, 245, 92, 74, 400, 18, 94, 40],
        ["NELSON_TEST", "2026-08-15 16:00", 0, 26, 24, 20, 250, 91, 74, 400, 14, 94, 34],
    ]
    with (OUT / "Weather.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Scenario", "datetime", "APCP", "TMP", "RH", "WS", "WD", "FFMC", "DMC", "DC", "ISI", "BUI", "FWI"])
        writer.writerows(weather)

    shutil.copyfile(
        ROOT / "Cell2Fire" / "data" / "9cellsC1" / "fbp_lookup_table.csv",
        OUT / "fbp_lookup_table.csv",
    )
    print(f"Created {OUT} ({cols} columns × {rows} rows); ignition cell {cell_id}.")


if __name__ == "__main__":
    main()
