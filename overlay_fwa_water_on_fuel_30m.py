#!/usr/bin/env python3
"""Overlay BC Freshwater Atlas major water features on the 30 m fuel raster."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely.geometry import shape


ROOT = Path(__file__).resolve().parent
RUN = ROOT / "runs" / "aoi-30m-mrdem-fuel30-48h-prevailing-single-center"
SOURCE_RASTER = RUN / "data" / "derived" / "fuel_30m.tif"
OUTPUT_RASTER = RUN / "data" / "derived" / "fuel_30m_hydro_named_mainstreams_falls_tributary.tif"
SUMMARY = RUN / "data" / "derived" / "hydro_named_mainstreams_falls_tributary_overlay_summary.json"
SOURCE_DIR = RUN / "data" / "source"
WATER_CODE = 102
STREAM_BUFFER_M = 15.0
STREAM_SOURCE = SOURCE_DIR / "fwa_named_main_streams.geojson"
TRIBUTARY_SOURCE = SOURCE_DIR / "fwa_falls_creek_main_tributary.geojson"


def features_from(path: Path) -> list[dict]:
    content = json.loads(path.read_text(encoding="utf-8"))
    if content.get("type") != "FeatureCollection":
        raise ValueError(f"Expected FeatureCollection in {path}")
    return content.get("features", [])


def main() -> None:
    lake_file = SOURCE_DIR / "fwa_lakes.geojson"
    if not STREAM_SOURCE.exists() or not TRIBUTARY_SOURCE.exists() or not lake_file.exists():
        raise SystemExit("Missing Freshwater Atlas named-stream, Falls Creek tributary, or lake GeoJSON files.")

    named_stream_features = features_from(STREAM_SOURCE)
    tributary_features = features_from(TRIBUTARY_SOURCE)
    stream_features = named_stream_features + tributary_features
    lake_features = features_from(lake_file)
    stream_geometries = [shape(feature["geometry"]).buffer(STREAM_BUFFER_M) for feature in stream_features]
    lake_geometries = [shape(feature["geometry"]) for feature in lake_features]

    with rasterio.open(SOURCE_RASTER) as source:
        fuel = source.read(1)
        profile = source.profile.copy()
        transform = source.transform
        nodata = source.nodata if source.nodata is not None else -9999

    stream_mask = rasterize(
        ((geometry, 1) for geometry in stream_geometries),
        out_shape=fuel.shape,
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)
    lake_mask = rasterize(
        ((geometry, 1) for geometry in lake_geometries),
        out_shape=fuel.shape,
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)

    valid = fuel != nodata
    water_mask = (stream_mask | lake_mask) & valid
    original_water = fuel == WATER_CODE
    added_water = water_mask & ~original_water
    fuel[water_mask] = WATER_CODE

    profile.update(
        driver="GTiff",
        count=1,
        dtype=fuel.dtype,
        nodata=nodata,
        compress="deflate",
        tiled=True,
    )
    with rasterio.open(OUTPUT_RASTER, "w", **profile) as target:
        target.write(fuel, 1)
        target.update_tags(
            HYDRO_SOURCE="BC Freshwater Atlas Stream Network and Lakes",
            HYDRO_STREAM_RULE=(
                "EDGE_TYPE 1000 (Stream - Main Flow) with GNIS_NAME IS NOT NULL, plus all available "
                "segments sharing BLUE_LINE_KEY 356567471 for the selected main tributary to Falls Creek"
            ),
            HYDRO_STREAM_BUFFER_M=str(STREAM_BUFFER_M),
            HYDRO_LAKE_RULE="All Freshwater Atlas lake polygons intersecting the fuel grid",
            WATER_FUEL_CODE=str(WATER_CODE),
            SOURCE_RASTER=str(SOURCE_RASTER.relative_to(ROOT)),
        )

    summary = {
        "source_raster": str(SOURCE_RASTER.relative_to(ROOT)),
        "output_raster": str(OUTPUT_RASTER.relative_to(ROOT)),
        "crs": "EPSG:3005",
        "cell_size_m": 30,
        "water_fuel_code": WATER_CODE,
        "named_main_stream_features": len(named_stream_features),
        "falls_creek_tributary_features": len(tributary_features),
        "stream_features": len(stream_features),
        "lake_features": len(lake_features),
        "stream_buffer_m": STREAM_BUFFER_M,
        "valid_cells": int(valid.sum()),
        "original_water_cells": int(original_water.sum()),
        "water_cells_after_overlay": int((fuel == WATER_CODE).sum()),
        "new_water_cells": int(added_water.sum()),
        "stream_cells_touched": int((stream_mask & valid).sum()),
        "lake_cells_touched": int((lake_mask & valid).sum()),
        "method": (
            "Named Stream - Main Flow features, all available segments of the selected main tributary to Falls Creek, "
            "and all lake geometries were rasterized onto the existing 30 m grid; intersecting valid cells were assigned "
            "FBP water/non-fuel code 102."
        ),
    }
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
