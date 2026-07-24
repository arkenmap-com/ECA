#!/usr/bin/env python3
"""Prepare the AOI BC DEM landscape, summer Smallwood P90 weather, and ignitions."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.fill import fillnodata
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform_geom
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parent
SOURCE_RUN = ROOT / "runs" / "aoi-25m-p90-smallwood"
RUN = ROOT / "runs" / "aoi-25m-bcdem-summer-p90"
RAW_WEATHER = SOURCE_RUN / "data" / "weather" / "raw"
DEM_SOURCE = SOURCE_RUN / "data" / "dem_bc25m" / "source"
DERIVED = RUN / "data" / "derived"
PREPARED = RUN / "data" / "weather" / "prepared"
IGNITIONS = RUN / "data" / "ignitions_500m.geojson"
CONFIG = ROOT / "examples" / "aoi-25m-bcdem-summer-p90.json"
CRS = "EPSG:3005"
CELL = 25.0
IGNITION_SPACING = 500.0
YEARS = set(range(2016, 2026))
HOURS = range(12, 18)
HOURLY = (
    "HOURLY_TEMPERATURE",
    "HOURLY_RELATIVE_HUMIDITY",
    "HOURLY_WIND_SPEED",
    "HOURLY_WIND_DIRECTION",
)
DAILY = (
    "FINE_FUEL_MOISTURE_CODE",
    "DUFF_MOISTURE_CODE",
    "DROUGHT_CODE",
    "INITIAL_SPREAD_INDEX",
    "BUILDUP_INDEX",
    "FIRE_WEATHER_INDEX",
)


def number(row: dict[str, str], field: str) -> float | None:
    raw = (row.get(field) or "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def load_aoi():
    content = json.loads((ROOT / "aoi.geojson").read_text(encoding="utf-8"))
    geometries = [shape(feature["geometry"]) for feature in content["features"]]
    aoi_ll = geometries[0]
    for geometry in geometries[1:]:
        aoi_ll = aoi_ll.union(geometry)
    forward = Transformer.from_crs("EPSG:4326", CRS, always_xy=True).transform
    return aoi_ll, transform(forward, aoi_ll)


def aligned_grid(aoi):
    minx, miny, maxx, maxy = aoi.bounds
    left = math.floor(minx / CELL) * CELL
    bottom = math.floor(miny / CELL) * CELL
    right = math.ceil(maxx / CELL) * CELL
    top = math.ceil(maxy / CELL) * CELL
    return left, bottom, right, top, int((right - left) / CELL), int((top - bottom) / CELL)


def warp(source: Path, destination: Path, transform_out, width: int, height: int, resampling, dtype, nodata):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(source) as src:
        target = np.full((height, width), nodata, dtype=dtype)
        reproject(
            source=rasterio.band(src, 1),
            destination=target,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform_out,
            dst_crs=CRS,
            src_nodata=src.nodata,
            dst_nodata=nodata,
            resampling=resampling,
        )
    return target


def warp_many(sources: list[Path], transform_out, width: int, height: int, resampling, dtype, nodata):
    target = np.full((height, width), nodata, dtype=dtype)
    for source in sources:
        with rasterio.open(source) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=target,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform_out,
                dst_crs=CRS,
                src_nodata=src.nodata,
                dst_nodata=nodata,
                resampling=resampling,
                init_dest_nodata=False,
            )
    return target


def write_raster(path: Path, values: np.ndarray, transform_out, nodata) -> None:
    with rasterio.open(
        path, "w", driver="GTiff", height=values.shape[0], width=values.shape[1],
        count=1, dtype=values.dtype, crs=CRS, transform=transform_out,
        nodata=nodata, compress="deflate", tiled=True,
    ) as target:
        target.write(values, 1)


def build_landscape(aoi_projected) -> tuple[int, int]:
    left, bottom, right, top, width, height = aligned_grid(aoi_projected)
    grid_transform = from_origin(left, top, CELL, CELL)
    mask = geometry_mask([mapping(aoi_projected)], (height, width), grid_transform, invert=True)

    fuel = warp(
        ROOT / "long-term/nelson-50km/data/raw/fuel_100m_50km_envelope.tif",
        DERIVED / "fuel_25m.tif", grid_transform, width, height,
        Resampling.nearest, np.int16, -9999,
    )
    fuel[~mask] = -9999
    write_raster(DERIVED / "fuel_25m.tif", fuel, grid_transform, -9999)

    dem_tiles = [
        DEM_SOURCE / "082f05_e" / "082f05_e.dem",
        DEM_SOURCE / "082f06_w" / "082f06_w.dem",
        DEM_SOURCE / "082f11_w" / "082f11_w.dem",
        DEM_SOURCE / "082f12_e" / "082f12_e.dem",
    ]
    missing = [str(path) for path in dem_tiles if not path.exists()]
    if missing:
        raise SystemExit(f"Missing GeoBC 25 m DEM tiles: {missing}")
    elevation = warp_many(
        dem_tiles, grid_transform, width, height, Resampling.bilinear, np.float32, -9999.0,
    )
    valid = mask & np.isfinite(elevation) & (elevation != -9999)
    terrain_surface = fillnodata(
        elevation.astype(np.float32),
        mask=valid.astype(np.uint8),
        max_search_distance=max(width, height),
        smoothing_iterations=0,
    ).astype(np.float64)
    elevation[~valid] = 0
    write_raster(DERIVED / "elevation_25m.tif", elevation.astype(np.float32), grid_transform, -9999.0)

    dz_dy, dz_dx = np.gradient(terrain_surface, CELL, CELL)
    slope = np.hypot(dz_dx, dz_dy) * 100.0
    aspect = (90.0 - np.degrees(np.arctan2(-dz_dy, dz_dx))) % 360.0
    slope[~valid] = 0
    aspect[~valid] = 0
    write_raster(DERIVED / "slope_percent_25m.tif", slope.astype(np.float32), grid_transform, -9999.0)
    write_raster(DERIVED / "aspect_degrees_25m.tif", aspect.astype(np.float32), grid_transform, -9999.0)
    terrain_summary = {
        "product": "Digital Elevation Model for British Columbia - CDED - 1:250,000",
        "producer": "GeoBC",
        "derivation": "CDED tiles converted from the provincial TRIM 1:20,000 DEM",
        "nominal_pixel_size_m": 25,
        "source_crs": "EPSG:4269",
        "analysis_crs": CRS,
        "resampling": "bilinear to the aligned 25 m BC Albers simulation grid",
        "slope_aspect": "recalculated from the reprojected elevation grid",
        "tiles": [path.name for path in dem_tiles],
        "source_url": "https://pub.data.gov.bc.ca/datasets/175624/82f/",
    }
    (DERIVED / "terrain_summary.json").write_text(json.dumps(terrain_summary, indent=2) + "\n", encoding="utf-8")
    return width, height


def build_weather() -> dict[str, object]:
    by_day: dict[str, dict[int, dict[str, str]]] = defaultdict(dict)
    source_files = []
    for path in sorted(RAW_WEATHER.glob("*_smallwood.csv")):
        if not path.stat().st_size:
            continue
        year = int(path.name[:4])
        if year not in YEARS:
            continue
        source_files.append(path.name)
        with path.open(newline="", encoding="utf-8-sig") as source:
            for row in csv.DictReader(source):
                if row.get("STATION_CODE") != "404":
                    continue
                timestamp = row["DATE_TIME"]
                if timestamp[4:6] not in {"06", "07", "08"}:
                    continue
                by_day[timestamp[:8]][int(timestamp[8:10])] = row

    accepted = []
    for date, hours in sorted(by_day.items()):
        noon = hours.get(12)
        if noon is None or any(hour not in hours for hour in HOURS):
            continue
        daily = [number(noon, field) for field in DAILY]
        if any(value is None for value in daily):
            continue
        if any(number(hours[hour], field) is None for hour in HOURS for field in HOURLY):
            continue
        accepted.append((date, hours, daily))
    if not accepted:
        raise SystemExit("No complete Smallwood weather days were found.")

    fwi_values = np.array([row[2][-1] for row in accepted], dtype=float)
    percentile = float(np.percentile(fwi_values, 90))
    selected = min(accepted, key=lambda row: (abs(float(row[2][-1]) - percentile), row[0]))
    date, hours, daily = selected
    ffmc, dmc, dc, isi, bui, fwi = daily
    scenario = f"404_P90_{date}"

    PREPARED.mkdir(parents=True, exist_ok=True)
    weather_rows = []
    for hour in HOURS:
        row = hours[hour]
        timestamp = datetime.strptime(row["DATE_TIME"], "%Y%m%d%H")
        weather_rows.append({
            "Scenario": scenario, "datetime": timestamp.strftime("%Y-%m-%d %H:00"),
            "APCP": number(row, "HOURLY_PRECIPITATION") or 0,
            "TMP": number(row, "HOURLY_TEMPERATURE"), "RH": number(row, "HOURLY_RELATIVE_HUMIDITY"),
            "WS": number(row, "HOURLY_WIND_SPEED"), "WD": number(row, "HOURLY_WIND_DIRECTION"),
            "FFMC": ffmc, "DMC": dmc, "DC": dc, "ISI": isi, "BUI": bui, "FWI": fwi,
        })
    with (PREPARED / "weather_library.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=weather_rows[0].keys())
        writer.writeheader()
        writer.writerows(weather_rows)
    scenario_row = {
        "scenario": scenario, "station_code": "404", "station_name": "SMALLWOOD",
        "date": date, "ffmc": ffmc, "dmc": dmc, "dc": dc, "isi": isi, "bui": bui, "fwi": fwi,
    }
    with (PREPARED / "weather_scenarios.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=scenario_row.keys())
        writer.writeheader()
        writer.writerow(scenario_row)
    summary = {
        "station": "404 SMALLWOOD", "period": "2016-2025", "months": "June-August",
        "complete_days": len(accepted), "percentile_metric": "daily noon FWI",
        "fwi_p90": percentile, "selected_observed_date": date, "selected_fwi": fwi,
        "selection_method": "complete observed six-hour day with FWI closest to the empirical 90th percentile",
        "source_files": source_files,
    }
    (PREPARED / "weather_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def build_ignitions(aoi_projected) -> int:
    minx, miny, maxx, maxy = aoi_projected.bounds
    start_x = math.ceil(minx / IGNITION_SPACING) * IGNITION_SPACING
    start_y = math.ceil(miny / IGNITION_SPACING) * IGNITION_SPACING
    reverse = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    features = []
    sequence = 0
    for x in np.arange(start_x, maxx + 0.1, IGNITION_SPACING):
        for y in np.arange(start_y, maxy + 0.1, IGNITION_SPACING):
            if not aoi_projected.covers(Point(float(x), float(y))):
                continue
            sequence += 1
            lon, lat = reverse.transform(float(x), float(y))
            features.append({
                "type": "Feature",
                "properties": {"GRID_ID": sequence, "GRID_X": float(x), "GRID_Y": float(y), "SPACING_M": 500},
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            })
    IGNITIONS.parent.mkdir(parents=True, exist_ok=True)
    IGNITIONS.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2) + "\n", encoding="utf-8")
    return len(features)


def write_config(ignition_count: int) -> None:
    config = {
        "name": "aoi-25m-bcdem-summer-p90",
        "display_name": "AOI — BC 25 m DEM, summer Smallwood P90",
        "scenario_description": "AOI at 25 m with GeoBC CDED/TRIM-derived DEM; June-August 2016-2025 Smallwood P90 FWI weather; exhaustive 500 m ignition grid",
        "analysis_crs": CRS,
        "study_area": {"aoi_geojson": "aoi.geojson"},
        "inputs": {
            "fuel_raster": "runs/aoi-25m-bcdem-summer-p90/data/derived/fuel_25m.tif",
            "elevation_raster": "runs/aoi-25m-bcdem-summer-p90/data/derived/elevation_25m.tif",
            "slope_raster": "runs/aoi-25m-bcdem-summer-p90/data/derived/slope_percent_25m.tif",
            "aspect_raster": "runs/aoi-25m-bcdem-summer-p90/data/derived/aspect_degrees_25m.tif",
            "weather_library": "runs/aoi-25m-bcdem-summer-p90/data/weather/prepared/weather_library.csv",
            "weather_scenarios": "runs/aoi-25m-bcdem-summer-p90/data/weather/prepared/weather_scenarios.csv",
            "ignitions_geojson": "runs/aoi-25m-bcdem-summer-p90/data/ignitions_500m.geojson",
            "fbp_lookup_table": "Cell2Fire/data/9cellsC1/fbp_lookup_table.csv",
        },
        "outputs": {
            "cell2fire_input_dir": "Cell2Fire/data/aoi-25m-bcdem-summer-p90",
            "output_dir": "runs/aoi-25m-bcdem-summer-p90/outputs",
            "web_map_dir": "runs/aoi-25m-bcdem-summer-p90/web-map",
        },
        "simulation": {
            "runs": ignition_count, "seed": 20260723, "workers": 4, "weather_hours": 6,
            "fire_period_length_hours": 1.0, "ros_cv": 0.0, "cell_size_m": 25,
            "ignition_sampling": "exhaustive",
            "scratch_root": "/private/tmp/fire-sim/aoi-25m-bcdem-summer-p90",
            "cell2fire_python": "Cell2Fire/.venv/bin/python",
            "cell2fire_main": "Cell2Fire/cell2fire/main.py",
            "results_dir": "/private/tmp/fire-sim/aoi-25m-bcdem-summer-p90/results",
        },
        "ignition_fields": {"fire_number": "GRID_ID"},
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    _, aoi_projected = load_aoi()
    width, height = build_landscape(aoi_projected)
    weather = build_weather()
    ignitions = build_ignitions(aoi_projected)
    write_config(ignitions)
    print(f"Prepared {width} x {height} 25 m landscape, {ignitions} 500 m ignitions, weather {weather['selected_observed_date']}.")


if __name__ == "__main__":
    main()
