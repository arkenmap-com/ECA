#!/usr/bin/env python3
"""Prepare a 48-hour single-ignition AOI scenario."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform

from prepare_aoi_24h_prevailing import (
    RAW_WEATHER,
    load_summer_winds,
    number,
    prevailing_wind,
)


ROOT = Path(__file__).resolve().parent
SOURCE_RUN = ROOT / "runs" / "aoi-25m-bcdem-summer-p90"
RUN_NAME = "aoi-25m-bcdem-summer-p90-48h-prevailing-single-sw"
LOCATION_SLUG = "southwest"
LOCATION_DISPLAY = "southwest-quadrant"
LOCATION_DEFINITION = "centre of bottom-left AOI bounding-box quadrant"
X_FRACTION = 0.25
Y_FRACTION = 0.25
RESULTS_DIRNAME = "results"
RUN = ROOT / "runs" / RUN_NAME
DERIVED = RUN / "data" / "derived"
PREPARED = RUN / "data" / "weather" / "prepared"
IGNITION = RUN / "data" / "ignition_single_sw.geojson"
CONFIG = ROOT / "examples" / f"{RUN_NAME}.json"
DATES = ("20180820", "20180821")


def load_aoi_projected():
    content = json.loads((ROOT / "aoi.geojson").read_text(encoding="utf-8"))
    geometry = shape(content["features"][0]["geometry"])
    for feature in content["features"][1:]:
        geometry = geometry.union(shape(feature["geometry"]))
    project = Transformer.from_crs("EPSG:4326", "EPSG:3005", always_xy=True).transform
    return geometry, transform(project, geometry)


def write_single_ignition() -> dict[str, float]:
    aoi_ll, aoi = load_aoi_projected()
    minx, miny, maxx, maxy = aoi.bounds
    requested = Point(minx + X_FRACTION * (maxx - minx), miny + Y_FRACTION * (maxy - miny))
    if not aoi.covers(requested):
        requested = aoi.boundary.interpolate(aoi.boundary.project(requested))
    reverse = Transformer.from_crs("EPSG:3005", "EPSG:4326", always_xy=True)
    lon, lat = reverse.transform(requested.x, requested.y)
    if not aoi_ll.buffer(1e-9).covers(Point(lon, lat)):
        raise SystemExit("Calculated ignition does not fall inside the AOI.")
    feature_collection = {
        "type": "FeatureCollection",
        "name": f"single {LOCATION_DISPLAY} ignition",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [{
            "type": "Feature",
            "properties": {
                "GRID_ID": "SW_QUADRANT_CENTER",
                "definition": LOCATION_DEFINITION,
                "requested_x_epsg3005": requested.x,
                "requested_y_epsg3005": requested.y,
            },
            "geometry": mapping(Point(lon, lat)),
        }],
    }
    IGNITION.parent.mkdir(parents=True, exist_ok=True)
    IGNITION.write_text(json.dumps(feature_collection, indent=2) + "\n", encoding="utf-8")
    return {"longitude": lon, "latitude": lat, "x_epsg3005": requested.x, "y_epsg3005": requested.y}


def load_weather() -> tuple[list[dict[str, str]], dict[str, dict[str, float]]]:
    path = RAW_WEATHER / "2018_smallwood.csv"
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            if row.get("STATION_CODE") == "404" and row.get("DATE_TIME", "")[:8] in DATES:
                rows.append(row)
    rows.sort(key=lambda row: row["DATE_TIME"])
    if len(rows) != 48:
        raise SystemExit(f"Expected 48 hourly records for {DATES}; found {len(rows)}.")
    daily = {}
    for date in DATES:
        noon = next(row for row in rows if row["DATE_TIME"] == f"{date}12")
        daily[date] = {
            "dmc": number(noon, "DUFF_MOISTURE_CODE"),
            "dc": number(noon, "DROUGHT_CODE"),
            "bui": number(noon, "BUILDUP_INDEX"),
        }
        if any(value is None for value in daily[date].values()):
            raise SystemExit(f"{date} is missing a daily noon fire-weather code.")
    required = (
        "HOURLY_PRECIPITATION",
        "HOURLY_TEMPERATURE",
        "HOURLY_RELATIVE_HUMIDITY",
        "HOURLY_WIND_SPEED",
        "HOURLY_FINE_FUEL_MOISTURE_CODE",
        "HOURLY_INITIAL_SPREAD_INDEX",
        "HOURLY_FIRE_WEATHER_INDEX",
    )
    for row in rows:
        missing = [field for field in required if number(row, field) is None]
        if missing:
            raise SystemExit(f"{row['DATE_TIME']} is missing hourly fields: {missing}")
    return rows, daily  # type: ignore[return-value]


def write_weather(prevailing: dict[str, object], rows, daily) -> None:
    PREPARED.mkdir(parents=True, exist_ok=True)
    scenario = "404_20180820_21_48H_PREVAILING"
    output = []
    for row in rows:
        timestamp = row["DATE_TIME"]
        day = timestamp[:8]
        output.append({
            "Scenario": scenario,
            "datetime": f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]} {timestamp[8:10]}:00",
            "APCP": number(row, "HOURLY_PRECIPITATION"),
            "TMP": number(row, "HOURLY_TEMPERATURE"),
            "RH": number(row, "HOURLY_RELATIVE_HUMIDITY"),
            "WS": number(row, "HOURLY_WIND_SPEED"),
            "WD": prevailing["applied_integer_direction_degrees_from"],
            "FFMC": number(row, "HOURLY_FINE_FUEL_MOISTURE_CODE"),
            "DMC": daily[day]["dmc"],
            "DC": daily[day]["dc"],
            "ISI": number(row, "HOURLY_INITIAL_SPREAD_INDEX"),
            "BUI": daily[day]["bui"],
            "FWI": number(row, "HOURLY_FIRE_WEATHER_INDEX"),
        })
    with (PREPARED / "weather_library.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=output[0])
        writer.writeheader()
        writer.writerows(output)
    noon = output[12]
    scenario_row = {
        "scenario": scenario, "station_code": "404", "station_name": "SMALLWOOD",
        "date": DATES[0], "ffmc": noon["FFMC"], "dmc": noon["DMC"], "dc": noon["DC"],
        "isi": noon["ISI"], "bui": noon["BUI"], "fwi": noon["FWI"],
    }
    with (PREPARED / "weather_scenarios.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=scenario_row)
        writer.writeheader()
        writer.writerow(scenario_row)
    summary = {
        "scenario": scenario,
        "period": "2018-08-20 00:00 through 2018-08-21 23:00",
        "hours": 48,
        "wind_direction_override": prevailing,
        "hourly_variables": [
            "precipitation", "temperature", "relative humidity", "wind speed",
            "Fine Fuel Moisture Code", "Initial Spread Index", "Fire Weather Index",
        ],
        "daily_variables": [
            "Duff Moisture Code", "Drought Code", "Build Up Index",
        ],
        "rationale": (
            "The observed two-day sequence preserves hourly weather variation while replacing direction "
            "with the wind-speed-weighted prevailing June-August direction from 2016-2025."
        ),
    }
    (PREPARED / "weather_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def copy_landscape() -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)
    for source in (SOURCE_RUN / "data" / "derived").iterdir():
        if source.is_file() and source.suffix in {".tif", ".json"}:
            shutil.copy2(source, DERIVED / source.name)


def write_config() -> None:
    config = {
        "name": RUN_NAME,
        "display_name": f"AOI - 48 h prevailing wind, single {LOCATION_DISPLAY} ignition",
        "scenario_description": (
            f"Single {LOCATION_DISPLAY} ignition; GeoBC 25 m terrain; observed Smallwood weather "
            "20-21 August 2018 with 193 degree prevailing wind direction"
        ),
        "analysis_crs": "EPSG:3005",
        "study_area": {"aoi_geojson": "aoi.geojson"},
        "inputs": {
            "fuel_raster": f"runs/{RUN_NAME}/data/derived/fuel_25m.tif",
            "elevation_raster": f"runs/{RUN_NAME}/data/derived/elevation_25m.tif",
            "slope_raster": f"runs/{RUN_NAME}/data/derived/slope_percent_25m.tif",
            "aspect_raster": f"runs/{RUN_NAME}/data/derived/aspect_degrees_25m.tif",
            "weather_library": f"runs/{RUN_NAME}/data/weather/prepared/weather_library.csv",
            "weather_scenarios": f"runs/{RUN_NAME}/data/weather/prepared/weather_scenarios.csv",
            "ignitions_geojson": str(IGNITION.relative_to(ROOT)),
            "fbp_lookup_table": "Cell2Fire/data/9cellsC1/fbp_lookup_table.csv",
        },
        "outputs": {
            "cell2fire_input_dir": f"Cell2Fire/data/{RUN_NAME}",
            "output_dir": f"runs/{RUN_NAME}/outputs",
            "web_map_dir": f"runs/{RUN_NAME}/web-map",
        },
        "simulation": {
            "runs": 1, "seed": 20260725, "workers": 1, "weather_hours": 48,
            "save_intermediate_grids": True,
            "fire_period_length_hours": 1.0, "ros_cv": 0.0, "cell_size_m": 25,
            "ignition_sampling": "exhaustive",
            "scratch_root": f"/private/tmp/fire-sim/{RUN_NAME}",
            "cell2fire_python": "Cell2Fire/.venv/bin/python",
            "cell2fire_main": "Cell2Fire/cell2fire/main.py",
            "results_dir": f"/private/tmp/fire-sim/{RUN_NAME}/{RESULTS_DIRNAME}",
        },
        "ignition_fields": {"fire_number": "GRID_ID"},
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    copy_landscape()
    location = write_single_ignition()
    prevailing = prevailing_wind(load_summer_winds())
    rows, daily = load_weather()
    write_weather(prevailing, rows, daily)
    write_config()
    summary = {
        "requested_location_definition": LOCATION_DEFINITION,
        "requested_location": location,
        "model_note": "The pipeline snaps the point to the nearest burnable cell during input preparation.",
    }
    (RUN / "data" / "ignition_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Prepared {RUN} and {CONFIG}")


if __name__ == "__main__":
    main()
