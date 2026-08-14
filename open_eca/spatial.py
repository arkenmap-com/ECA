"""Reusable vector operations for the open-source ECA workflow."""

from __future__ import annotations

from collections.abc import Iterable

import geopandas as gpd
from shapely.geometry.base import BaseGeometry


_GEOMETRY_DIMENSIONS = {
    "Point": 0, "MultiPoint": 0,
    "LineString": 1, "LinearRing": 1, "MultiLineString": 1,
    "Polygon": 2, "MultiPolygon": 2,
}


def _geometry_dimension(geometry: BaseGeometry | None) -> int:
    """Return the greatest topological dimension represented by a geometry."""
    if geometry is None or geometry.is_empty:
        return -1
    dimension = _GEOMETRY_DIMENSIONS.get(geometry.geom_type)
    if dimension is not None:
        return dimension
    parts = getattr(geometry, "geoms", ())
    return max((_geometry_dimension(part) for part in parts), default=-1)


def polygonal_features(features: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return polygon components while preserving their source attributes."""
    result = features.loc[~features.geometry.is_empty & ~features.geometry.isna()].copy()
    # Exploding decomposes GeometryCollections as well as multipart geometry.
    # Repeat for the rare nested collection produced by make-valid operations.
    for _ in range(4):
        if result.empty or not (result.geom_type == "GeometryCollection").any():
            break
        result = result.explode(ignore_index=True)
    result = result.loc[result.geom_type.isin(("Polygon", "MultiPolygon"))]
    return result.reset_index(drop=True)[features.columns].copy()


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
    """Intersect features with a boundary, retaining source attributes only.

    Intersection is applied directly instead of through ``GeoDataFrame.overlay``
    because public or uploaded layers can legitimately contain mixed geometry
    families. Lower-dimensional boundary-touch artifacts are removed per input
    feature, while polygon, line, and point records can coexist safely.
    """
    if features.crs is None:
        raise ValueError("Features have no CRS.")
    boundary = _as_boundary(boundary).to_crs(features.crs)
    clipped = features.copy()
    dimension_field = "_eca_source_dimension"
    while dimension_field in clipped.columns:
        dimension_field = f"_{dimension_field}"
    clipped[dimension_field] = clipped.geometry.map(_geometry_dimension)
    clipped.geometry = clipped.geometry.make_valid().intersection(boundary.geometry.iloc[0])
    clipped = clipped.loc[~clipped.geometry.is_empty & ~clipped.geometry.isna()]
    for _ in range(4):
        if clipped.empty or not (clipped.geom_type == "GeometryCollection").any():
            break
        clipped = clipped.explode(ignore_index=True)
    clipped = clipped.loc[
        clipped.geometry.map(_geometry_dimension) == clipped[dimension_field]
    ]
    return clipped.drop(columns=dimension_field).reset_index(drop=True)[features.columns].copy()


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
