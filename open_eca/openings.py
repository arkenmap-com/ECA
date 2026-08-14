"""Opening precedence, spatial splitting, and ECA-area calculations."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Tuple, Union

import geopandas as gpd
import pandas as pd

from open_eca.spatial import clip_to_boundary


BASE_FIELDS = ("OPENING_ID", "CROWN_CLOSURE", "PROJ_HEIGHT_1", "Info", "ECAsrc")
# QGIS LTR 3.40 bundles Python 3.9, so keep this alias compatible with it.
OpeningLayer = Union[
    Tuple[gpd.GeoDataFrame, str],
    Tuple[gpd.GeoDataFrame, str, bool],
]


def _normalise_openings(
    openings: gpd.GeoDataFrame,
    source_label: str,
    zero_recovery_inputs: bool,
) -> gpd.GeoDataFrame:
    """Align opening fields while retaining all source attributes for review."""
    if openings.crs is None:
        raise ValueError(f"{source_label} has no CRS.")
    result = openings.copy()
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
    return erased.explode(ignore_index=True)[features.columns].copy()


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
    """Merge VRI, RESULTS, and FTA openings using legacy ID precedence.

    VRI keeps records with matching ``OPENING_ID``. New RESULTS or FTA records
    erase their overlap from the accumulated base and are added as unrecovered
    openings (zero crown closure and projected height).
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
        current = _concat_openings([_erase(current, selected), selected], current.crs)
    return add_opening_area(current)


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
    return add_opening_area(current)


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
    return add_opening_area(current)


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
    return add_opening_area(split)


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
