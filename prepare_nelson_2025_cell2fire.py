#!/usr/bin/env python3
"""Create Cell2Fire inputs and a 1,000-run manifest for the Nelson 2025 scenario."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from pyproj import Transformer


ROOT = Path(__file__).resolve().parent
STUDY = ROOT / "long-term" / "nelson-50km"
DERIVED = STUDY / "data" / "derived"
WEATHER = STUDY / "data" / "prepared"
IGNITIONS = STUDY / "data" / "ignitions" / "bcws_historical_ignitions_50km.geojson"
OUT = ROOT / "Cell2Fire" / "data" / "nelson-50km-2025"

# 11 and 105 occupy 27 of 160,000 cells. They are not represented in the
# current Cell2Fire lookup table, so they are explicitly treated as non-fuel
# pending a fuel-class crosswalk review instead of being silently misclassified.
FUEL_MAP = {
    2: ("C2", ""), 3: ("C3", ""), 4: ("C4", ""), 5: ("C5", ""),
    7: ("C7", ""), 13: ("D1", ""), 31: ("O1a", ""),
    101: ("NF", ""), 102: ("NF", ""), 11: ("NF", ""), 105: ("NF", ""),
    415: ("M1", "15"), 625: ("M1", "25"), 650: ("M1", "50"),
    675: ("M1", "75"), -9999: ("NF", ""),
}


def raster_values(path: Path) -> tuple[np.ndarray, dict[str, object]]:
    info = json.loads(subprocess.check_output(["gdalinfo", "-json", str(path)], text=True))
    with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as temp:
        xyz = Path(temp.name)
    try:
        subprocess.run(["gdal_translate", "-q", "-of", "XYZ", str(path), str(xyz)], check=True)
        values = np.loadtxt(xyz, usecols=2).reshape(info["size"][1], info["size"][0])
    finally:
        xyz.unlink(missing_ok=True)
    return values, info


def nearest_burnable(row: int, col: int, burnable: np.ndarray) -> tuple[int, int] | None:
    rows, cols = burnable.shape
    for radius in range(0, 6):
        for r in range(max(0, row - radius), min(rows, row + radius + 1)):
            for c in range(max(0, col - radius), min(cols, col + radius + 1)):
                if burnable[r, c]:
                    return r, c
    return None


def main() -> None:
    fuel, info = raster_values(DERIVED / "fuel_250m_50km.tif")
    elevation, _ = raster_values(DERIVED / "elevation_250m_50km.tif")
    slope, _ = raster_values(DERIVED / "slope_percent_250m_50km.tif")
    aspect, _ = raster_values(DERIVED / "aspect_degrees_250m_50km.tif")
    rows, cols = fuel.shape
    origin_x, cell_x, _, origin_y, _, cell_y = info["geoTransform"]

    unknown = sorted(set(np.unique(fuel.astype(int))) - set(FUEL_MAP))
    if unknown:
        raise ValueError(f"Unmapped fuel values: {unknown}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "Weathers").mkdir(exist_ok=True)
    with (OUT / "Forest.asc").open("w", encoding="utf-8") as target:
        target.write(f"ncols {cols}\n")
        target.write(f"nrows {rows}\n")
        target.write(f"xllcorner {origin_x}\n")
        target.write(f"yllcorner {origin_y + rows * cell_y}\n")
        target.write(f"cellsize {abs(cell_x)}\n")
        target.write("NODATA_value -9999\n")
        for line in fuel.astype(int):
            target.write(" ".join(map(str, line)) + "\n")

    x = origin_x + cell_x * (np.arange(cols) + 0.5)
    y = origin_y + cell_y * (np.arange(rows) + 0.5)
    xx, yy = np.meshgrid(x, y)
    lon, lat = Transformer.from_crs(3005, 4326, always_xy=True).transform(xx, yy)
    columns = [
        "fueltype", "mon", "jd", "M", "jd_min", "lat", "lon", "elev",
        "ffmc", "ws", "waz", "bui", "ps", "saz", "pc", "pdf", "gfl",
        "cur", "time", "pattern",
    ]
    with (OUT / "Data.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        for raw, z, slp, asp, latitude, longitude in zip(
            fuel.ravel().astype(int), elevation.ravel(), slope.ravel(), aspect.ravel(),
            lat.ravel(), lon.ravel(), strict=True,
        ):
            fuel_type, percent_conifer = FUEL_MAP[raw]
            writer.writerow({
                "fueltype": fuel_type, "mon": "8", "jd": "220",
                "lat": f"{latitude:.5f}", "lon": f"{longitude:.5f}",
                "elev": f"{z:.1f}", "ps": f"{max(slp, 0):.2f}",
                "saz": f"{0 if asp < 0 else asp:.1f}", "pc": percent_conifer,
                "gfl": "0.75", "time": "20",
            })

    with (WEATHER / "weather_scenarios.csv").open(newline="", encoding="utf-8") as source:
        scenarios = list(csv.DictReader(source))
    with (WEATHER / "weather_library.csv").open(newline="", encoding="utf-8") as source:
        by_scenario: dict[str, list[dict[str, str]]] = {}
        for record in csv.DictReader(source):
            by_scenario.setdefault(record["Scenario"], []).append(record)
    weather_manifest: list[dict[str, object]] = []
    headers = ["Scenario", "datetime", "APCP", "TMP", "RH", "WS", "WD", "FFMC", "DMC", "DC", "ISI", "BUI", "FWI"]
    for index, scenario in enumerate(scenarios, start=1):
        name = str(scenario["scenario"])
        records = by_scenario[name]
        with (OUT / "Weathers" / f"Weather{index}.csv").open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=headers)
            writer.writeheader()
            writer.writerows(records)
        weather_manifest.append({"weather_index": index, **scenario})
    with (OUT / "weather_manifest.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=weather_manifest[0].keys())
        writer.writeheader()
        writer.writerows(weather_manifest)

    fire_data = json.loads(IGNITIONS.read_text(encoding="utf-8"))["features"]
    burnable = np.vectorize(lambda code: FUEL_MAP[int(code)][0] != "NF")(fuel)
    rng = np.random.default_rng(20250716)
    chosen_weather = rng.integers(1, len(weather_manifest) + 1, size=1000)
    chosen_ignitions = rng.integers(0, len(fire_data), size=1000)
    run_rows = []
    to_grid = Transformer.from_crs(4326, 3005, always_xy=True)
    for run_id, (weather_index, ignition_index) in enumerate(zip(chosen_weather, chosen_ignitions), start=1):
        point = fire_data[int(ignition_index)]
        longitude, latitude = point["geometry"]["coordinates"]
        gx, gy = to_grid.transform(longitude, latitude)
        row, col = int((origin_y - gy) / abs(cell_y)), int((gx - origin_x) / cell_x)
        if not (0 <= row < rows and 0 <= col < cols):
            continue
        snapped = nearest_burnable(row, col, burnable)
        if not snapped:
            continue
        row, col = snapped
        properties = point["properties"]
        run_rows.append({
            "run_id": run_id, "weather_index": int(weather_index),
            "scenario": weather_manifest[int(weather_index) - 1]["scenario"],
            "fire_number": properties["FIRE_NUMBER"], "fire_year": properties["FIRE_YEAR"],
            "fire_cause": properties["FIRE_CAUSE"], "ignition_lat": latitude,
            "ignition_lon": longitude, "cell_id": row * cols + col + 1,
        })
    with (OUT / "run_manifest.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=run_rows[0].keys())
        writer.writeheader()
        writer.writerows(run_rows)

    shutil.copyfile(ROOT / "Cell2Fire" / "data" / "9cellsC1" / "fbp_lookup_table.csv", OUT / "fbp_lookup_table.csv")
    (OUT / "input_metadata.json").write_text(json.dumps({
        "grid": {"rows": rows, "columns": cols, "cell_size_m": abs(cell_x)},
        "weather_scenarios": len(weather_manifest),
        "planned_runs": len(run_rows),
        "fuel_classes_treated_as_nonfuel": {"11": 1, "105": 26},
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Created {OUT}: {len(weather_manifest)} weather files; {len(run_rows)} planned runs.")


if __name__ == "__main__":
    main()
