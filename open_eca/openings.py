"""Opening precedence, spatial splitting, and ECA-area calculations."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional, Tuple, Union

import geopandas as gpd
import pandas as pd
from shapely.geometry.base import BaseGeometry

from open_eca.spatial import clip_to_boundary, polygonal_features


BASE_FIELDS = ("OPENING_ID", "CROWN_CLOSURE", "PROJ_HEIGHT_1", "Info", "ECAsrc")
# QGIS LTR 3.40 bundles Python 3.9, so keep this alias compatible with it.
OpeningLayer = Union[
    Tuple[gpd.GeoDataFrame, str],
    Tuple[gpd.GeoDataFrame, str, bool],
]


def _polygon_parts(geometry: Optional[BaseGeometry]) -> list[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type in {"MultiPolygon", "GeometryCollection"}:
        return [part for geometry_part in geometry.geoms for part in _polygon_parts(geometry_part)]
    return []


def _remove_internal_overlaps(features: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Give earlier records precedence and remove later positive-area overlap."""
    if features.empty:
        return features.copy()
    features = features.copy()
    features.geometry = features.geometry.make_valid()
    features = polygonal_features(features)
    geometry_name = features.geometry.name
    records: list[dict] = []
    occupied: Optional[BaseGeometry] = None
    for _, row in features.iterrows():
        geometry = row.geometry
        remainder = geometry if occupied is None else geometry.difference(occupied)
        for part in _polygon_parts(remainder):
            record = row.to_dict()
            record[geometry_name] = part
            records.append(record)
        occupied = geometry if occupied is None else occupied.union(geometry)
    if not records:
        return features.iloc[0:0].copy()
    return gpd.GeoDataFrame(
        records, columns=features.columns, geometry=geometry_name, crs=features.crs,
    ).reset_index(drop=True)


def assert_non_overlapping(
    features: gpd.GeoDataFrame,
    label: str,
    tolerance_square_metres: float = 1e-6,
) -> None:
    """Raise when polygon interiors overlap by more than floating-point noise."""
    polygons = polygonal_features(features)
    if len(polygons) < 2:
        return
    if polygons.crs is None:
        raise ValueError(f"{label} has no CRS.")
    measured = polygons.to_crs("EPSG:3005").reset_index(drop=True)
    for position, geometry in enumerate(measured.geometry):
        candidates = measured.sindex.query(geometry, predicate="intersects")
        for candidate_position in candidates:
            if candidate_position <= position:
                continue
            overlap_area = float(geometry.intersection(measured.geometry.iloc[candidate_position]).area)
            if overlap_area > tolerance_square_metres:
                raise ValueError(
                    f"{label} contains at least {overlap_area:.6f} m² of overlapping polygon area."
                )


def _normalise_openings(
    openings: gpd.GeoDataFrame,
    source_label: str,
    zero_recovery_inputs: bool,
) -> gpd.GeoDataFrame:
    """Align opening fields while retaining all source attributes for review."""
    if openings.crs is None:
        raise ValueError(f"{source_label} has no CRS.")
    # ECA is an area calculation. Public WFS responses and user files can
    # contain stray lines, points, or GeometryCollection parts; retaining them
    # would make later polygon overlays fail or create zero-area records.
    result = _remove_internal_overlaps(polygonal_features(openings))
    for field in BASE_FIELDS:
        if field not in result:
            result[field] = None
    result["ECAsrc"] = source_label
    if zero_recovery_inputs:
        result["CROWN_CLOSURE"] = 0
        result["PROJ_HEIGHT_1"] = 0
    return result


def _erase(features: gpd.GeoDataFrame, erase_features: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return source attributes for feature parts outside the erase geometry."""
    if features.empty or erase_features.empty:
        return features.copy()
    erase_features = erase_features.to_crs(features.crs)
    # A single dissolved mask is both faster and more robust than GeoPandas'
    # pair-by-pair overlay reduction. Some valid BCGW polygons trigger a GEOS
    # dimension assertion only after several sequential difference operations.
    mask = erase_features.geometry.union_all()
    erased = features.copy()
    erased["geometry"] = erased.geometry.difference(mask)
    usable = erased.geometry.map(lambda geometry: geometry is not None and not geometry.is_empty)
    erased = erased.loc[usable]
    return polygonal_features(erased.explode(ignore_index=True)[features.columns])


def _concat_openings(parts: Iterable[gpd.GeoDataFrame], crs: object) -> gpd.GeoDataFrame:
    parts = list(parts)
    non_empty = [part for part in parts if not part.empty]
    if not non_empty:
        # Keep the normalized opening schema for a valid zero-opening result.
        # A geometry-only frame is later (incorrectly) diagnosed as missing
        # recovery inputs such as crown closure and projected height.
        if parts:
            return parts[0].iloc[0:0].copy()
        return gpd.GeoDataFrame(geometry=[], crs=crs)
    return gpd.GeoDataFrame(pd.concat(non_empty, ignore_index=True), crs=crs)


def merge_base_openings(
    vri: gpd.GeoDataFrame,
    results: gpd.GeoDataFrame | None = None,
    fta: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Merge openings with strict VRI, RESULTS, then FTA precedence.

    VRI retains its complete footprint. New RESULTS or FTA records are added as
    unrecovered openings (zero crown closure and projected height) only for
    area not already represented by a higher-priority source. Matching opening
    IDs remain represented exclusively by the higher-priority record.
    """
    current = _normalise_openings(vri, "VRI Openings and Burns", False)
    if "OPENING_ID" not in vri:
        raise ValueError("VRI openings must contain OPENING_ID.")
    for supplemental, label in ((results, "Results"), (fta, "FTA Pending Blocks")):
        if supplemental is None or supplemental.empty:
            continue
        candidate = _normalise_openings(supplemental, label, True).to_crs(current.crs)
        if "OPENING_ID" not in supplemental:
            raise ValueError(f"{label} must contain OPENING_ID.")
        existing_ids = set(current["OPENING_ID"].dropna())
        selected = candidate.loc[
            candidate["OPENING_ID"].isna() | ~candidate["OPENING_ID"].isin(existing_ids)
        ].copy()
        current = _concat_openings([current, _erase(selected, current)], current.crs)
    result = add_opening_area(current)
    assert_non_overlapping(result, "Merged openings")
    return result


def append_lower_priority(
    base_openings: gpd.GeoDataFrame,
    layers: Iterable[OpeningLayer],
) -> gpd.GeoDataFrame:
    """Append lower-priority sources only where they do not overlap prior data."""
    current = base_openings.copy()
    for item in layers:
        layer, label, *recovery_setting = item
        zero_recovery = recovery_setting[0] if recovery_setting else True
        candidate = _normalise_openings(layer, label, zero_recovery).to_crs(current.crs)
        current = _concat_openings([current, _erase(candidate, current)], current.crs)
    result = add_opening_area(current)
    assert_non_overlapping(result, "Completed openings")
    return result


def build_other_openings(
    main_openings: gpd.GeoDataFrame,
    layers: Iterable[tuple[gpd.GeoDataFrame, str]],
) -> gpd.GeoDataFrame:
    """Build non-recovering openings without overlap with main or prior layers."""
    current = gpd.GeoDataFrame(geometry=[], crs=main_openings.crs)
    for layer, label in layers:
        candidate = _normalise_openings(layer, label, True).to_crs(main_openings.crs)
        candidate = _erase(candidate, main_openings)
        candidate = _erase(candidate, current)
        current = _concat_openings([current, candidate], main_openings.crs)
    result = add_opening_area(current)
    assert_non_overlapping(result, "Other openings")
    return result


def split_openings(
    openings: gpd.GeoDataFrame,
    h60_zones: gpd.GeoDataFrame,
    subbasins: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Split openings by H60 zone and sub-basin, then calculate hectare areas."""
    if "ELEVATION" not in h60_zones:
        raise ValueError("H60 zones must contain ELEVATION.")
    if "Sub_Basin" not in subbasins:
        raise ValueError("Subbasins must contain Sub_Basin.")
    h60 = gpd.overlay(openings, h60_zones[["ELEVATION", "geometry"]].to_crs(openings.crs), how="intersection")
    split = gpd.overlay(h60, subbasins[["Sub_Basin", "geometry"]].to_crs(openings.crs), how="intersection")
    result = add_opening_area(split)
    assert_non_overlapping(result, "H60 and sub-basin opening splits")
    return result


def add_opening_area(openings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Calculate hectares and ECA hectares when a recovery value is present."""
    result = openings.copy()
    result["Hectares"] = result.geometry.area / 10_000
    if "Recovery" in result:
        result["ECA_Hectares"] = result["Hectares"] * (1 - result["Recovery"] / 100)
    return result


def clip_sources_to_watershed(
    sources: Iterable[tuple[gpd.GeoDataFrame, str]],
    watershed: gpd.GeoDataFrame,
) -> dict[str, gpd.GeoDataFrame]:
    """Clip named source layers to a watershed before opening assembly."""
    return {name: clip_to_boundary(source, watershed) for source, name in sources}
