#!/usr/bin/env python3
"""Prepare the 30 m fuel + MRDEM terrain version of the central 48-hour run."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.fill import fillnodata
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parent
NAME = "aoi-30m-mrdem-fuel30-48h-prevailing-single-center"
RUN = ROOT / "runs" / NAME
SOURCE = RUN / "data" / "source"
DERIVED = RUN / "data" / "derived"
WEATHER_SOURCE = (
    ROOT / "runs" / "aoi-25m-bcdem-summer-p90-48h-prevailing-single-center"
    / "data" / "weather" / "prepared"
)
WEATHER = RUN / "data" / "weather" / "prepared"
IGNITION = RUN / "data" / "ignition_single_center.geojson"
CONFIG = ROOT / "examples" / f"{NAME}.json"
CRS = "EPSG:3005"
CELL = 30.0


def load_aoi():
    content = json.loads((ROOT / "aoi.geojson").read_text(encoding="utf-8"))
    geographic = shape(content["features"][0]["geometry"])
    for feature in content["features"][1:]:
        geographic = geographic.union(shape(feature["geometry"]))
    forward = Transformer.from_crs("EPSG:4326", CRS, always_xy=True).transform
    return geographic, transform(forward, geographic)


def aligned_grid(aoi):
    minx, miny, maxx, maxy = aoi.bounds
    left = math.floor(minx / CELL) * CELL
    bottom = math.floor(miny / CELL) * CELL
    right = math.ceil(maxx / CELL) * CELL
    top = math.ceil(maxy / CELL) * CELL
    return left, bottom, right, top, int((right - left) / CELL), int((top - bottom) / CELL)


def warp(source: Path, transform_out, width: int, height: int, resampling, dtype, nodata):
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


def write_raster(path: Path, values: np.ndarray, transform_out, nodata) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", height=values.shape[0], width=values.shape[1],
        count=1, dtype=values.dtype, crs=CRS, transform=transform_out,
        nodata=nodata, compress="deflate", tiled=True,
    ) as target:
        target.write(values, 1)


def build_landscape(aoi) -> tuple[int, int]:
    left, bottom, right, top, width, height = aligned_grid(aoi)
    transform_out = from_origin(left, top, CELL, CELL)
    mask = geometry_mask([mapping(aoi)], (height, width), transform_out, invert=True)

    fuel = warp(
        SOURCE / "fuel_30m_epsg3978.tif", transform_out, width, height,
        Resampling.nearest, np.int16, -9999,
    )
    fuel[~mask] = -9999
    write_raster(DERIVED / "fuel_30m.tif", fuel, transform_out, -9999)

    elevation = warp(
        SOURCE / "mrdem_30m_dtm_epsg3979.tif", transform_out, width, height,
        Resampling.bilinear, np.float32, -9999.0,
    )
    valid = mask & np.isfinite(elevation) & (elevation != -9999)
    terrain_surface = fillnodata(
        elevation.astype(np.float32),
        mask=valid.astype(np.uint8),
        max_search_distance=max(width, height),
        smoothing_iterations=0,
    ).astype(np.float64)
    elevation[~valid] = 0
    write_raster(DERIVED / "elevation_30m.tif", elevation.astype(np.float32), transform_out, -9999.0)

    dz_dy, dz_dx = np.gradient(terrain_surface, CELL, CELL)
    slope = np.hypot(dz_dx, dz_dy) * 100.0
    aspect = (90.0 - np.degrees(np.arctan2(-dz_dy, dz_dx))) % 360.0
    slope[~valid] = 0
    aspect[~valid] = 0
    write_raster(DERIVED / "slope_percent_30m.tif", slope.astype(np.float32), transform_out, -9999.0)
    write_raster(DERIVED / "aspect_degrees_30m.tif", aspect.astype(np.float32), transform_out, -9999.0)

    unique_fuels = sorted(int(value) for value in np.unique(fuel[mask]))
    terrain_values = elevation[valid]
    metadata = {
        "grid": {
            "analysis_crs": CRS, "cell_size_m": CELL,
            "rows": height, "columns": width,
        },
        "fuel": {
            "product": "CFFDRS Fire Behaviour Prediction Fuel Types 2024, 30 m",
            "producer": "Natural Resources Canada / Canadian Forest Service",
            "source_crs": "EPSG:3978",
            "source_resolution_m": 30,
            "resampling": "nearest neighbour to aligned 30 m BC Albers grid",
            "source_service": "https://cwfis.cfs.nrcan.gc.ca/geoserver/public/cffdrs_fbp_fuel_types/wcs",
            "fuel_codes": unique_fuels,
        },
        "terrain": {
            "product": "MRDEM-30 DTM, CanElevation Series",
            "producer": "Natural Resources Canada",
            "source_crs": "EPSG:3979",
            "source_resolution_m": 30,
            "vertical_datum": "CGVD2013",
            "resampling": "bilinear to aligned 30 m BC Albers grid",
            "slope_aspect": "recalculated from reprojected elevation",
            "source": "https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.vrt",
            "elevation_min_m": float(terrain_values.min()),
            "elevation_max_m": float(terrain_values.max()),
        },
    }
    (DERIVED / "source_summary.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return width, height


def write_ignition(aoi_geographic, aoi) -> dict[str, float]:
    minx, miny, maxx, maxy = aoi.bounds
    requested = Point((minx + maxx) / 2, (miny + maxy) / 2)
    if not aoi.covers(requested):
        requested = aoi.representative_point()
    reverse = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    longitude, latitude = reverse.transform(requested.x, requested.y)
    if not aoi_geographic.buffer(1e-9).covers(Point(longitude, latitude)):
        raise SystemExit("Central ignition point is outside the AOI.")
    content = {
        "type": "FeatureCollection",
        "name": "single central ignition",
        "features": [{
            "type": "Feature",
            "properties": {
                "GRID_ID": "AOI_CENTER",
                "definition": "centre of the AOI projected bounding box",
            },
            "geometry": mapping(Point(longitude, latitude)),
        }],
    }
    IGNITION.parent.mkdir(parents=True, exist_ok=True)
    IGNITION.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    return {"longitude": longitude, "latitude": latitude, "x_epsg3005": requested.x, "y_epsg3005": requested.y}


def copy_weather() -> None:
    WEATHER.mkdir(parents=True, exist_ok=True)
    for source in WEATHER_SOURCE.iterdir():
        if source.is_file():
            shutil.copy2(source, WEATHER / source.name)


def write_config() -> None:
    config = {
        "name": NAME,
        "display_name": "AOI - native 30 m fuel and MRDEM, 48 h central ignition",
        "scenario_description": (
            "Single central ignition; native 30 m NRCan fuel and MRDEM terrain; observed Smallwood "
            "weather 20-21 August 2018 with 193 degree prevailing wind direction"
        ),
        "analysis_crs": CRS,
        "study_area": {"aoi_geojson": "aoi.geojson"},
        "inputs": {
            "fuel_raster": f"runs/{NAME}/data/derived/fuel_30m.tif",
            "elevation_raster": f"runs/{NAME}/data/derived/elevation_30m.tif",
            "slope_raster": f"runs/{NAME}/data/derived/slope_percent_30m.tif",
            "aspect_raster": f"runs/{NAME}/data/derived/aspect_degrees_30m.tif",
            "weather_library": f"runs/{NAME}/data/weather/prepared/weather_library.csv",
            "weather_scenarios": f"runs/{NAME}/data/weather/prepared/weather_scenarios.csv",
            "ignitions_geojson": f"runs/{NAME}/data/ignition_single_center.geojson",
            "fbp_lookup_table": "Cell2Fire/data/9cellsC1/fbp_lookup_table.csv",
        },
        "outputs": {
            "cell2fire_input_dir": f"Cell2Fire/data/{NAME}",
            "output_dir": f"runs/{NAME}/outputs",
            "web_map_dir": f"runs/{NAME}/web-map",
        },
        "simulation": {
            "runs": 1, "seed": 20260726, "workers": 1, "weather_hours": 48,
            "save_intermediate_grids": True,
            "fire_period_length_hours": 1.0, "ros_cv": 0.0, "cell_size_m": 30,
            "ignition_sampling": "exhaustive",
            "scratch_root": f"/private/tmp/fire-sim/{NAME}",
            "cell2fire_python": "Cell2Fire/.venv/bin/python",
            "cell2fire_main": "Cell2Fire/cell2fire/main.py",
            "results_dir": f"/private/tmp/fire-sim/{NAME}/results",
        },
        "ignition_fields": {"fire_number": "GRID_ID"},
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    aoi_geographic, aoi = load_aoi()
    width, height = build_landscape(aoi)
    ignition = write_ignition(aoi_geographic, aoi)
    copy_weather()
    write_config()
    summary = {
        "grid": f"{width} x {height} at 30 m",
        "ignition": ignition,
        "weather": "same 48-hour prevailing-wind sequence as the 25 m comparison run",
    }
    (RUN / "data" / "preparation_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
