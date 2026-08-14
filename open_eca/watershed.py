"""Open-source watershed and sub-basin preparation for the ECA workflow."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd


WORKING_CRS = "EPSG:3005"


@dataclass(frozen=True)
class WatershedResult:
    """Canonical ECA watershed outputs and their basic metrics."""

    basin: str
    basin_area_ha: float
    watershed_layer: str = "watershed"
    subbasin_layer: str = "subbasins"


def _require_column(frame: gpd.GeoDataFrame, column: str) -> None:
    if column not in frame.columns:
        raise ValueError(f"Input watershed is missing required field: {column}")


def _normalise_names(values: gpd.GeoSeries, fallback: str) -> gpd.GeoSeries:
    names = values.fillna("").astype(str).str.strip()
    return names.mask(names == "", fallback)


def prepare_watershed(
    input_path: Path,
    basin_field: str,
    subbasin_field: str,
    output_path: Path,
    overwrite: bool = False,
) -> WatershedResult:
    """Dissolve a watershed, standardize sub-basins, and write a GeoPackage.

    Input geometry is projected into BC Albers (EPSG:3005) before areas are
    calculated. The result has the stable field names used by later Open ECA
    modules: ``Watershed``, ``Sub_Basin``, ``BasinArea`` and
    ``SubBasinArea``.
    """
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output_path}. Use --overwrite to replace it.")

    source = gpd.read_file(input_path)
    if source.empty:
        raise ValueError("Input watershed contains no features.")
    if source.crs is None:
        raise ValueError("Input watershed has no CRS. Define it before running ECA.")
    _require_column(source, basin_field)
    _require_column(source, subbasin_field)

    source = source.to_crs(WORKING_CRS)
    basin_values = _normalise_names(source[basin_field], "")
    unique_basins = sorted(value for value in basin_values.unique() if value)
    if len(unique_basins) != 1:
        raise ValueError(
            "Input watershed must contain exactly one non-empty basin name; "
            f"found {len(unique_basins)}: {unique_basins!r}"
        )
    basin = unique_basins[0]

    source = source.loc[~source.geometry.is_empty & source.geometry.notna()].copy()
    if source.empty:
        raise ValueError("Input watershed has no usable geometry.")
    source["Watershed"] = basin
    source["Sub_Basin"] = _normalise_names(source[subbasin_field], basin)

    watershed = source[["Watershed", "geometry"]].dissolve(
        by="Watershed", as_index=False,
    )
    basin_area_ha = float(watershed.geometry.area.iloc[0] / 10_000)
    watershed["BasinArea"] = basin_area_ha

    subbasins = source.drop(columns=[column for column in (basin_field, subbasin_field)
                                     if column not in {"Watershed", "Sub_Basin"}]).copy()
    subbasins["SubBasinArea"] = subbasins.geometry.area / 10_000

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(".tmp.gpkg")
    if temporary_path.exists():
        temporary_path.unlink()
    try:
        watershed.to_file(temporary_path, layer="watershed", driver="GPKG")
        subbasins.to_file(temporary_path, layer="subbasins", driver="GPKG", mode="a")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return WatershedResult(basin=basin, basin_area_ha=basin_area_ha)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Input watershed vector file.")
    parser.add_argument("--basin-field", required=True)
    parser.add_argument("--subbasin-field", required=True)
    parser.add_argument("--output", type=Path, required=True, help="Output GeoPackage path.")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = prepare_watershed(
            args.input, args.basin_field, args.subbasin_field, args.output, args.overwrite,
        )
    except (FileExistsError, ValueError) as error:
        parser.error(str(error))
    print(f"Prepared {result.basin} ({result.basin_area_ha:.2f} ha) in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
