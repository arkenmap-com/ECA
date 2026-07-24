#!/usr/bin/env python3
"""Prepare the 24-hour AOI scenario with speed-weighted prevailing summer wind."""

from __future__ import annotations

import csv
import json
import math
import shutil
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_RUN = ROOT / "runs" / "aoi-25m-bcdem-summer-p90"
RUN = ROOT / "runs" / "aoi-25m-bcdem-summer-p90-24h-prevailing"
RAW_WEATHER = ROOT / "runs" / "aoi-25m-p90-smallwood" / "data" / "weather" / "raw"
DERIVED = RUN / "data" / "derived"
PREPARED = RUN / "data" / "weather" / "prepared"
IGNITIONS = RUN / "data" / "ignitions_500m.geojson"
CONFIG = ROOT / "examples" / "aoi-25m-bcdem-summer-p90-24h-prevailing.json"
YEARS = range(2016, 2026)
TARGET_DATE = "20180820"


def number(row: dict[str, str], field: str) -> float | None:
    raw = (row.get(field) or "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def load_summer_winds() -> list[tuple[float, float]]:
    observations: list[tuple[float, float]] = []
    for year in YEARS:
        path = RAW_WEATHER / f"{year}_smallwood.csv"
        with path.open(newline="", encoding="utf-8-sig") as source:
            for row in csv.DictReader(source):
                timestamp = row.get("DATE_TIME", "")
                if row.get("STATION_CODE") != "404" or timestamp[4:6] not in {"06", "07", "08"}:
                    continue
                speed = number(row, "HOURLY_WIND_SPEED")
                direction = number(row, "HOURLY_WIND_DIRECTION")
                if speed is None or direction is None or speed <= 0:
                    continue
                observations.append((direction % 360.0, speed))
    if not observations:
        raise SystemExit("No usable Smallwood summer wind observations were found.")
    return observations


def prevailing_wind(observations: list[tuple[float, float]]) -> dict[str, object]:
    east = sum(speed * math.sin(math.radians(direction)) for direction, speed in observations)
    north = sum(speed * math.cos(math.radians(direction)) for direction, speed in observations)
    total_weight = sum(speed for _, speed in observations)
    direction = math.degrees(math.atan2(east, north)) % 360.0
    concentration = math.hypot(east, north) / total_weight
    sectors = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
               "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
    counts = Counter(sectors[int((value + 11.25) // 22.5) % 16] for value, _ in observations)
    return {
        "direction_degrees_from": direction,
        "applied_integer_direction_degrees_from": int(round(direction)),
        "direction_label": "south-southwest",
        "observation_count": len(observations),
        "calculation": "wind-speed-weighted circular mean of non-calm hourly wind directions",
        "period": "June-August 2016-2025",
        "station": "404 SMALLWOOD",
        "resultant_vector_concentration": concentration,
        "most_frequent_22_5_degree_sector": counts.most_common(1)[0][0],
        "most_frequent_sector_count": counts.most_common(1)[0][1],
        "most_frequent_sector_fraction": counts.most_common(1)[0][1] / len(observations),
        "rationale": (
            "Wind speed is used as the weight because stronger winds contribute more to directional "
            "fire-spread forcing than calm or light-wind observations. The full summer record is used "
            "instead of the selected day's direction so the result represents prevailing severe-season "
            "flow rather than one day's trajectory."
        ),
        "direction_convention": "meteorological direction the wind comes from, clockwise from north",
    }


def target_day() -> tuple[list[dict[str, str]], dict[str, float]]:
    path = RAW_WEATHER / "2018_smallwood.csv"
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            if row.get("STATION_CODE") == "404" and row.get("DATE_TIME", "").startswith(TARGET_DATE):
                rows.append(row)
    rows.sort(key=lambda row: row["DATE_TIME"])
    if len(rows) != 24 or [int(row["DATE_TIME"][8:10]) for row in rows] != list(range(24)):
        raise SystemExit(f"Expected 24 complete hourly records for {TARGET_DATE}; found {len(rows)}.")
    noon = rows[12]
    daily_fields = {
        "dmc": "DUFF_MOISTURE_CODE",
        "dc": "DROUGHT_CODE",
        "bui": "BUILDUP_INDEX",
    }
    daily = {key: number(noon, source) for key, source in daily_fields.items()}
    if any(value is None for value in daily.values()):
        raise SystemExit("The target day's noon DMC, DC, or BUI value is missing.")
    required_hourly = (
        "HOURLY_PRECIPITATION",
        "HOURLY_TEMPERATURE",
        "HOURLY_RELATIVE_HUMIDITY",
        "HOURLY_WIND_SPEED",
        "HOURLY_FINE_FUEL_MOISTURE_CODE",
        "HOURLY_INITIAL_SPREAD_INDEX",
        "HOURLY_FIRE_WEATHER_INDEX",
    )
    for row in rows:
        missing = [field for field in required_hourly if number(row, field) is None]
        if missing:
            raise SystemExit(f"{row['DATE_TIME']} is missing hourly fields: {missing}")
    return rows, daily  # type: ignore[return-value]


def copy_landscape() -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)
    for source in (SOURCE_RUN / "data" / "derived").iterdir():
        if source.is_file() and source.suffix in {".tif", ".json"}:
            shutil.copy2(source, DERIVED / source.name)
    IGNITIONS.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_RUN / "data" / "ignitions_500m.geojson", IGNITIONS)


def write_weather(prevailing: dict[str, object], raw_rows: list[dict[str, str]], daily: dict[str, float]) -> None:
    PREPARED.mkdir(parents=True, exist_ok=True)
    scenario = "404_P90_20180820_24H_PREVAILING"
    applied_direction = prevailing["applied_integer_direction_degrees_from"]
    weather_rows = []
    for row in raw_rows:
        timestamp = row["DATE_TIME"]
        weather_rows.append({
            "Scenario": scenario,
            "datetime": f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]} {timestamp[8:10]}:00",
            "APCP": number(row, "HOURLY_PRECIPITATION"),
            "TMP": number(row, "HOURLY_TEMPERATURE"),
            "RH": number(row, "HOURLY_RELATIVE_HUMIDITY"),
            "WS": number(row, "HOURLY_WIND_SPEED"),
            "WD": applied_direction,
            "FFMC": number(row, "HOURLY_FINE_FUEL_MOISTURE_CODE"),
            "DMC": daily["dmc"],
            "DC": daily["dc"],
            "ISI": number(row, "HOURLY_INITIAL_SPREAD_INDEX"),
            "BUI": daily["bui"],
            "FWI": number(row, "HOURLY_FIRE_WEATHER_INDEX"),
        })
    with (PREPARED / "weather_library.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=weather_rows[0])
        writer.writeheader()
        writer.writerows(weather_rows)
    scenario_row = {
        "scenario": scenario,
        "station_code": "404",
        "station_name": "SMALLWOOD",
        "date": TARGET_DATE,
        "ffmc": weather_rows[12]["FFMC"],
        "dmc": daily["dmc"],
        "dc": daily["dc"],
        "isi": weather_rows[12]["ISI"],
        "bui": daily["bui"],
        "fwi": weather_rows[12]["FWI"],
    }
    with (PREPARED / "weather_scenarios.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=scenario_row)
        writer.writeheader()
        writer.writerow(scenario_row)
    summary = {
        "scenario": scenario,
        "target_observed_day": "2018-08-20",
        "hours": 24,
        "preserved_hourly_variables": [
            "precipitation", "temperature", "relative humidity", "wind speed",
            "Fine Fuel Moisture Code", "Initial Spread Index", "Fire Weather Index",
        ],
        "fixed_daily_variables": ["Duff Moisture Code", "Drought Code", "Build Up Index"],
        "wind_direction_override": prevailing,
        "note": (
            "The day's observed hourly wind directions were replaced with the prevailing direction. "
            "Hourly fire-weather codes were used where the source supplied them; daily drought and "
            "buildup codes were held at the observed noon values."
        ),
    }
    (PREPARED / "weather_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def write_config() -> None:
    name = "aoi-25m-bcdem-summer-p90-24h-prevailing"
    config = {
        "name": name,
        "display_name": "AOI - BC 25 m DEM, summer P90, 24 h prevailing wind",
        "scenario_description": (
            "AOI at 25 m with GeoBC CDED/TRIM-derived DEM; observed 20 August 2018 "
            "weather over 24 hours with speed-weighted prevailing summer wind direction; "
            "exhaustive 500 m ignition grid"
        ),
        "analysis_crs": "EPSG:3005",
        "study_area": {"aoi_geojson": "aoi.geojson"},
        "inputs": {
            "fuel_raster": f"runs/{name}/data/derived/fuel_25m.tif",
            "elevation_raster": f"runs/{name}/data/derived/elevation_25m.tif",
            "slope_raster": f"runs/{name}/data/derived/slope_percent_25m.tif",
            "aspect_raster": f"runs/{name}/data/derived/aspect_degrees_25m.tif",
            "weather_library": f"runs/{name}/data/weather/prepared/weather_library.csv",
            "weather_scenarios": f"runs/{name}/data/weather/prepared/weather_scenarios.csv",
            "ignitions_geojson": f"runs/{name}/data/ignitions_500m.geojson",
            "fbp_lookup_table": "Cell2Fire/data/9cellsC1/fbp_lookup_table.csv",
        },
        "outputs": {
            "cell2fire_input_dir": f"Cell2Fire/data/{name}",
            "output_dir": f"runs/{name}/outputs",
            "web_map_dir": f"runs/{name}/web-map",
        },
        "simulation": {
            "runs": 1028,
            "seed": 20260724,
            "workers": 8,
            "weather_hours": 24,
            "fire_period_length_hours": 1.0,
            "ros_cv": 0.0,
            "cell_size_m": 25,
            "ignition_sampling": "exhaustive",
            "aggregation_run_limit": 500,
            "scratch_root": f"/private/tmp/fire-sim/{name}",
            "cell2fire_python": "Cell2Fire/.venv/bin/python",
            "cell2fire_main": "Cell2Fire/cell2fire/main.py",
            "results_dir": f"/private/tmp/fire-sim/{name}/results",
        },
        "ignition_fields": {"fire_number": "GRID_ID"},
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    observations = load_summer_winds()
    prevailing = prevailing_wind(observations)
    raw_rows, daily = target_day()
    copy_landscape()
    write_weather(prevailing, raw_rows, daily)
    write_config()
    print(json.dumps(prevailing, indent=2))
    print(f"Prepared {RUN} and {CONFIG}")


if __name__ == "__main__":
    main()
