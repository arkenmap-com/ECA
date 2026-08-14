"""Reusable vector operations for the open-source ECA workflow."""

from __future__ import annotations

from collections.abc import Iterable

import geopandas as gpd
from shapely.geometry.base import BaseGeometry


def _as_boundary(boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if boundary.empty:
        raise ValueError("Boundary contains no features.")
    if boundary.crs is None:
        raise ValueError("Boundary has no CRS.")
    geometry = boundary.geometry.union_all()
    return gpd.GeoDataFrame(geometry=[geometry], crs=boundary.crs)


def clip_to_boundary(
    features: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Intersect features with a boundary, retaining source attributes only."""
    if features.crs is None:
        raise ValueError("Features have no CRS.")
    boundary = _as_boundary(boundary).to_crs(features.crs)
    clipped = gpd.overlay(
        features,
        boundary,
        how="intersection",
        keep_geom_type=False,
    )
    return clipped[features.columns].copy()


def buffer_transport(
    layers: Iterable[tuple[gpd.GeoDataFrame, float]],
    boundary: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Buffer centerlines by supplied half-widths, dissolve, then clip.

    ``layers`` contains ``(features, half_width_metres)`` pairs. Inputs must be
    in a projected CRS with metre units; ECA uses EPSG:3005.
    """
    boundary = _as_boundary(boundary)
    buffered: list[BaseGeometry] = []
    for features, half_width in layers:
        if half_width <= 0:
            raise ValueError("Transport buffer distance must be positive.")
        if features.crs is None:
            raise ValueError("Transport features have no CRS.")
        reprojected = features.to_crs(boundary.crs)
        buffered.extend(geometry.buffer(half_width) for geometry in reprojected.geometry if geometry)

    if not buffered:
        return gpd.GeoDataFrame(geometry=[], crs=boundary.crs)
    dissolved = gpd.GeoDataFrame(geometry=[gpd.GeoSeries(buffered).union_all()], crs=boundary.crs)
    return clip_to_boundary(dissolved, boundary)
