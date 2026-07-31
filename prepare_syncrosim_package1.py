#!/usr/bin/env python3
"""Assemble the SyncroSim Package 1 data bundle for the Nelson AOI."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parent
PACKAGE_NAME = "aoi-30m-mrdem-fuel30-p90-24h-1000m-falls-tributary"
PACKAGE = ROOT / "syncrosim" / "package1" / PACKAGE_NAME
INPUTS = PACKAGE / "inputs"
HYDRO = PACKAGE / "hydro"

BASE_RUN = ROOT / "runs" / "aoi-30m-mrdem-fuel30-48h-prevailing-single-center"
WEATHER_RUN = ROOT / "runs" / "aoi-30m-mrdem-fuel30-hydro-24h-p90-single-center"
FUEL = BASE_RUN / "data" / "derived" / "fuel_30m_hydro_named_mainstreams_falls_tributary.tif"
SOURCE = BASE_RUN / "data" / "source"
CRS = "EPSG:3005"
IGNITION_SPACING_M = 1000.0


def load_aoi() -> tuple[object, object]:
    content = json.loads((ROOT / "aoi.geojson").read_text(encoding="utf-8"))
    geographic = shape(content["features"][0]["geometry"])
    for feature in content["features"][1:]:
        geographic = geographic.union(shape(feature["geometry"]))
    forward = Transformer.from_crs("EPSG:4326", CRS, always_xy=True).transform
    return geographic, transform(forward, geographic)


def build_ignitions(aoi_projected) -> int:
    minx, miny, maxx, maxy = aoi_projected.bounds
    start_x = math.ceil(minx / IGNITION_SPACING_M) * IGNITION_SPACING_M
    start_y = math.ceil(miny / IGNITION_SPACING_M) * IGNITION_SPACING_M
    reverse = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    features = []
    sequence = 0
    x = start_x
    while x <= maxx + 0.1:
        y = start_y
        while y <= maxy + 0.1:
            point = Point(float(x), float(y))
            if aoi_projected.covers(point):
                sequence += 1
                longitude, latitude = reverse.transform(float(x), float(y))
                features.append({
                    "type": "Feature",
                    "properties": {
                        "GRID_ID": sequence,
                        "GRID_X": float(x),
                        "GRID_Y": float(y),
                        "SPACING_M": int(IGNITION_SPACING_M),
                        "definition": "Projected 1,000 m grid point inside the AOI; Cell2Fire snaps it to the nearest burnable cell.",
                    },
                    "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                })
            y += IGNITION_SPACING_M
        x += IGNITION_SPACING_M
    (INPUTS / "ignitions_1000m.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "name": "1000 m ignition grid", "features": features}, indent=2) + "\n",
        encoding="utf-8",
    )
    with (INPUTS / "ignitions_1000m.csv").open("w", encoding="utf-8") as target:
        target.write("GRID_ID,GRID_X,GRID_Y,SPACING_M,longitude,latitude\n")
        for feature in features:
            props = feature["properties"]
            lon, lat = feature["geometry"]["coordinates"]
            target.write(f"{props['GRID_ID']},{props['GRID_X']},{props['GRID_Y']},{props['SPACING_M']},{lon},{lat}\n")
    return len(features)


def copy_inputs() -> None:
    INPUTS.mkdir(parents=True, exist_ok=True)
    HYDRO.mkdir(parents=True, exist_ok=True)
    copies = {
        FUEL: INPUTS / FUEL.name,
        BASE_RUN / "data" / "derived" / "elevation_30m.tif": INPUTS / "elevation_30m.tif",
        BASE_RUN / "data" / "derived" / "slope_percent_30m.tif": INPUTS / "slope_percent_30m.tif",
        BASE_RUN / "data" / "derived" / "aspect_degrees_30m.tif": INPUTS / "aspect_degrees_30m.tif",
        ROOT / "aoi.geojson": INPUTS / "aoi.geojson",
        WEATHER_RUN / "data" / "weather" / "prepared" / "weather_library.csv": INPUTS / "weather_library.csv",
        WEATHER_RUN / "data" / "weather" / "prepared" / "weather_scenarios.csv": INPUTS / "weather_scenarios.csv",
        ROOT / "Cell2Fire" / "data" / "9cellsC1" / "fbp_lookup_table.csv": INPUTS / "fbp_lookup_table.csv",
        SOURCE / "fwa_named_main_streams.geojson": HYDRO / "fwa_named_main_streams.geojson",
        SOURCE / "fwa_lakes.geojson": HYDRO / "fwa_lakes.geojson",
        SOURCE / "fwa_falls_creek_main_tributary.geojson": HYDRO / "fwa_falls_creek_main_tributary.geojson",
        BASE_RUN / "data" / "derived" / "hydro_named_mainstreams_falls_tributary_overlay_summary.json": HYDRO / "overlay_summary.json",
    }
    for source, destination in copies.items():
        if not source.exists():
            raise SystemExit(f"Missing required input: {source}")
        shutil.copy2(source, destination)


def write_config(ignition_count: int) -> None:
    config = {
        "name": PACKAGE_NAME,
        "display_name": "SyncroSim Package 1 - 30 m fuel, 24 h P90, 1,000 m ignition grid",
        "scenario_description": (
            "Package 1 input data only; native 30 m NRCan FBP fuel with named Freshwater Atlas main streams, all lakes, "
            "and the selected main tributary to Falls Creek assigned water fuel code 102; 24 hourly Smallwood records "
            "from 20 August 2018, the observed day nearest the June-August 2016-2025 daily noon FWI P90."
        ),
        "analysis_crs": CRS,
        "study_area": {"aoi_geojson": f"syncrosim/package1/{PACKAGE_NAME}/inputs/aoi.geojson"},
        "inputs": {
            "fuel_raster": f"syncrosim/package1/{PACKAGE_NAME}/inputs/{FUEL.name}",
            "elevation_raster": f"syncrosim/package1/{PACKAGE_NAME}/inputs/elevation_30m.tif",
            "slope_raster": f"syncrosim/package1/{PACKAGE_NAME}/inputs/slope_percent_30m.tif",
            "aspect_raster": f"syncrosim/package1/{PACKAGE_NAME}/inputs/aspect_degrees_30m.tif",
            "weather_library": f"syncrosim/package1/{PACKAGE_NAME}/inputs/weather_library.csv",
            "weather_scenarios": f"syncrosim/package1/{PACKAGE_NAME}/inputs/weather_scenarios.csv",
            "ignitions_geojson": f"syncrosim/package1/{PACKAGE_NAME}/inputs/ignitions_1000m.geojson",
            "fbp_lookup_table": f"syncrosim/package1/{PACKAGE_NAME}/inputs/fbp_lookup_table.csv",
        },
        "outputs": {
            "cell2fire_input_dir": f"syncrosim/package1/{PACKAGE_NAME}/cell2fire",
            "output_dir": f"syncrosim/package1/{PACKAGE_NAME}/outputs",
            "web_map_dir": f"syncrosim/package1/{PACKAGE_NAME}/web-map",
        },
        "simulation": {
            "runs": ignition_count,
            "seed": 20260730,
            "workers": 1,
            "weather_hours": 24,
            "fire_period_length_hours": 1.0,
            "ros_cv": 0.0,
            "cell_size_m": 30,
            "ignition_sampling": "exhaustive",
            "scratch_root": f"/private/tmp/fire-sim/{PACKAGE_NAME}",
            "cell2fire_python": "Cell2Fire/.venv/bin/python",
            "cell2fire_main": "Cell2Fire/cell2fire/main.py",
        },
        "ignition_fields": {"fire_number": "GRID_ID"},
    }
    (PACKAGE / "package1_config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    metadata = {
        "package": "SyncroSim Package 1 data bundle",
        "name": PACKAGE_NAME,
        "analysis_crs": CRS,
        "cell_size_m": 30,
        "ignition_spacing_m": int(IGNITION_SPACING_M),
        "ignition_points": ignition_count,
        "weather_hours": 24,
        "weather_scenario": "404_P90_20180820_24H_PREVAILING",
        "water_fuel_code": 102,
        "water_inputs": {
            "named_main_stream_features": 231,
            "all_lake_features": 42,
            "falls_creek_main_tributary_blue_line_key": 356567471,
            "falls_creek_main_tributary_segments": 12,
        },
        "note": "Package data only; no fire simulation was executed by this preparation script.",
    }
    (PACKAGE / "package1_manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    _, aoi_projected = load_aoi()
    copy_inputs()
    count = build_ignitions(aoi_projected)
    write_config(count)
    print(json.dumps({"package": str(PACKAGE.relative_to(ROOT)), "ignition_points": count}, indent=2))


if __name__ == "__main__":
    main()
