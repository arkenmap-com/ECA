"""Raster-based H60 preparation for the open-source ECA workflow."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.mask import mask
from shapely.geometry import shape


@dataclass(frozen=True)
class H60Result:
    """Outputs from a watershed-clipped DEM H60 calculation."""

    percentile_40th: float
    clipped_dem: Path
    zones: Path


def _boundary_in_raster_crs(boundary: gpd.GeoDataFrame, raster_crs: object) -> gpd.GeoDataFrame:
    if boundary.empty:
        raise ValueError("Watershed boundary contains no features.")
    if boundary.crs is None:
        raise ValueError("Watershed boundary has no CRS.")
    if raster_crs is None:
        raise ValueError("DEM has no CRS.")
    return boundary.to_crs(raster_crs)


def clip_dem(dem_path: Path, boundary: gpd.GeoDataFrame, output_path: Path) -> Path:
    """Clip a DEM to a watershed boundary and write a float GeoTIFF."""
    with rasterio.open(dem_path) as source:
        boundary = _boundary_in_raster_crs(boundary, source.crs)
        data, transform = mask(source, boundary.geometry, crop=True, filled=False)
        profile = source.profile.copy()
        profile.update(
            driver="GTiff",
            dtype="float32",
            count=1,
            height=data.shape[1],
            width=data.shape[2],
            transform=transform,
            nodata=-9999.0,
            compress="deflate",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output_path, "w", **profile) as destination:
            destination.write(data[0].filled(-9999.0).astype("float32"), 1)
    return output_path


def percentile_elevation(dem_path: Path, percentile: float = 40) -> float:
    """Calculate an elevation percentile while excluding nodata and NaN cells."""
    if not 0 <= percentile <= 100:
        raise ValueError("Percentile must be between 0 and 100.")
    with rasterio.open(dem_path) as source:
        values = source.read(1, masked=True)
    valid = values.compressed()
    valid = valid[np.isfinite(valid)]
    if valid.size == 0:
        raise ValueError("DEM has no valid elevation cells.")
    return float(np.percentile(valid, percentile))


def h60_zones(dem_path: Path, elevation: float) -> gpd.GeoDataFrame:
    """Polygonize a DEM into H60 Below and H60 Above zones."""
    with rasterio.open(dem_path) as source:
        values = source.read(1, masked=True)
        valid = ~np.ma.getmaskarray(values) & np.isfinite(values.filled(np.nan))
        classified = np.where(values.filled(np.nan) <= elevation, 0, 1).astype("uint8")
        geometries = []
        for geometry, value in shapes(classified, mask=valid, transform=source.transform):
            geometries.append({
                "ELEVATION": "H60 Below" if value == 0 else "H60 Above",
                "geometry": shape(geometry),
            })
        zones = gpd.GeoDataFrame(geometries, crs=source.crs)
    if zones.empty:
        raise ValueError("DEM has no valid cells to polygonize.")
    zones = zones.dissolve(by="ELEVATION", as_index=False)
    # DEMs uploaded through the web app may be geographic or use non-metre
    # projected units. Calculate area in BC Albers rather than native pixels.
    zones["H60Area"] = zones.to_crs("EPSG:3005").geometry.area / 10_000
    return zones


def whole_watershed_zone(watershed: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return one analysis zone when elevation/H60 analysis is not requested.

    This is intentionally not labelled as an H60 zone. It lets screening ECA
    runs proceed without a DEM while making the omitted hydrologic split clear
    in both the output layers and reports.
    """
    if watershed.empty:
        raise ValueError("Watershed boundary contains no features.")
    zone = watershed[["geometry"]].copy()
    zone["ELEVATION"] = "Entire Watershed"
    zone["H60Area"] = zone.geometry.area / 10_000
    return zone[["ELEVATION", "H60Area", "geometry"]]


def derive_h60(
    dem_path: Path,
    watershed: gpd.GeoDataFrame,
    clipped_dem_path: Path,
    zones_path: Path,
) -> H60Result:
    """Create a clipped DEM and its H60 elevation-zone GeoPackage."""
    clip_dem(dem_path, watershed, clipped_dem_path)
    elevation = percentile_elevation(clipped_dem_path, 40)
    zones = h60_zones(clipped_dem_path, elevation)
    temporary_path = zones_path.with_suffix(".tmp.gpkg")
    if temporary_path.exists():
        temporary_path.unlink()
    try:
        zones.to_file(temporary_path, layer="h60_zones", driver="GPKG")
        os.replace(temporary_path, zones_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return H60Result(elevation, clipped_dem_path, zones_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem", type=Path, required=True)
    parser.add_argument("--watershed", type=Path, required=True, help="GeoPackage containing watershed geometry.")
    parser.add_argument("--watershed-layer", default="watershed")
    parser.add_argument("--clipped-dem", type=Path, required=True)
    parser.add_argument("--zones", type=Path, required=True, help="Output H60 GeoPackage.")
    args = parser.parse_args(argv)
    try:
        result = derive_h60(
            args.dem, gpd.read_file(args.watershed, layer=args.watershed_layer),
            args.clipped_dem, args.zones,
        )
    except (ValueError, rasterio.RasterioError) as error:
        parser.error(str(error))
    print(f"H60 elevation: {result.percentile_40th:.2f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
