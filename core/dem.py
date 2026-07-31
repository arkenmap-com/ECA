"""
DEM and elevation analysis operations.

Handles DEM clipping, percentile calculation, contour line generation,
H60 split, aspect and slope raster creation.
"""

import arcpy
import os
import numpy as np
from arcpy.sa import (
    Int, Aspect, Slope, Reclassify, RemapRange,
)

from core.config import (
    FLD_ELEVATION, FLD_H60_AREA,
    ASPECT_REMAP, SLOPE_REMAP,
)
from core.workspace import (
    FC_H60_LINE, FC_H60_SPLIT, FC_ASPECT, FC_SLOPE, gdb_fc,
)
from core.utils import safe_add_field, calc_area_hectares


def check_border(watershed_path, us_border_path):
    """Determine if the watershed crosses the US/Canada border.

    Returns ``"default"`` or ``"cross_border"`` — use with
    ``database.get_dem_by_condition()`` to resolve the correct DEM.
    """
    # Make a feature layer so SelectLayerByLocation works
    ws_lyr = "memory\\ws_border_check"
    arcpy.management.MakeFeatureLayer(watershed_path, ws_lyr)

    border_lyr = "memory\\border_check"
    arcpy.management.MakeFeatureLayer(us_border_path, border_lyr)

    select = arcpy.management.SelectLayerByLocation(
        ws_lyr, "CROSSED_BY_THE_OUTLINE_OF", border_lyr,
    )
    count = int(arcpy.GetCount_management(select)[0])
    arcpy.management.SelectLayerByAttribute(ws_lyr, "CLEAR_SELECTION")

    if count == 0:
        arcpy.AddMessage("Watershed does NOT cross USA/Canada Border, TRIM DEM is used")
        return "default"
    else:
        arcpy.AddMessage("Watershed crosses USA/Canada Border, SRTM DEM is used")
        return "cross_border"


def clip_dem(watershed, input_dem, output_folder):
    """Clip the DEM raster to the watershed polygon. Returns the output path."""
    dem_path = os.path.join(output_folder, "dem")
    arcpy.Clip_management(
        input_dem, "", dem_path, watershed,
        "", "ClippingGeometry", "NO_MAINTAIN_EXTENT",
    )
    return dem_path


def buffer_watershed(watershed, buffer_distance=20):
    """Buffer the watershed for contour line generation. Returns the buffer path."""
    buff = "memory\\shedBuffer"
    arcpy.analysis.Buffer(watershed, buff, buffer_distance, "", "", "ALL")
    return buff


def calc_percentile(dem, output_folder=None, percentile=40):
    """Calculate the Nth percentile elevation value from a DEM raster.

    If *output_folder* is provided, creates a temporary integer DEM there
    (needed for large rasters). Otherwise works in memory.

    Returns the percentile elevation value as a float.
    """
    dem_int = Int(dem)

    if output_folder:
        dem_int_path = os.path.join(output_folder, "demInt")
        dem_int.save(dem_int_path)
        dem_arr = arcpy.RasterToNumPyArray(dem_int_path, nodata_to_value=-999)
        arcpy.management.Delete(dem_int_path)
    else:
        dem_arr = arcpy.RasterToNumPyArray(dem_int, nodata_to_value=-999)

    masked = np.ma.masked_values(dem_arr, -999)
    value = np.percentile(masked.compressed(), percentile)
    arcpy.AddMessage(f"The {percentile}th percentile value is {int(value)}")
    return value


def draw_contour_line(dem, elevation, watershed, output_gdb):
    """Create a contour line at the given elevation and clip to watershed.

    Writes the result to *output_gdb*/H60_Line.
    """
    pre_contour = "memory\\preContour"
    h60_line_fc = gdb_fc(output_gdb, FC_H60_LINE)

    arcpy.AddMessage("Creating the H60 line")
    arcpy.ddd.ContourList(arcpy.Raster(dem), pre_contour, str(int(elevation)))
    arcpy.analysis.Clip(pre_contour, watershed, h60_line_fc, "")


def split_h60(watershed, dem, elevation, output_gdb, basin_area):
    """Split the watershed into H60 Above / H60 Below polygons.

    Writes H60Split to *output_gdb*.
    Returns the path to the H60Split feature class.
    """
    shed_split = "memory\\shedSplit"
    h60_dissolve = "memory\\H60Dissolve"
    h60_split_fc = gdb_fc(output_gdb, FC_H60_SPLIT)

    # Reclassify DEM into above/below
    safe_add_field(dem, FLD_ELEVATION, "TEXT", field_length=20)
    expression = (
        f"def elev(v):\n"
        f"    if v <= {elevation}:\n"
        f"        return 'H60 Below'\n"
        f"    else:\n"
        f"        return 'H60 Above'"
    )
    arcpy.management.CalculateField(
        dem, FLD_ELEVATION, "elev(!VALUE!)", "PYTHON3", expression,
    )
    arcpy.conversion.RasterToPolygon(dem, shed_split, "NO_SIMPLIFY", FLD_ELEVATION)
    arcpy.management.Dissolve(shed_split, h60_dissolve, FLD_ELEVATION)
    arcpy.analysis.Clip(h60_dissolve, watershed, h60_split_fc, "")

    # Add area fields
    calc_area_hectares(h60_split_fc, FLD_H60_AREA)

    # Delete the classified DEM (no longer needed)
    arcpy.management.Delete(dem)

    return h60_split_fc


def split_h60_final(watershed, dem, elevation, output_gdb, basin_area):
    """Split H60 for the Final tool - also returns above/below area strings."""
    h60_split_fc = split_h60(watershed, dem, elevation, output_gdb, basin_area)

    # Add text fields for labelling
    safe_add_field(h60_split_fc, "H60_Area", "TEXT", field_length=20)
    safe_add_field(h60_split_fc, "H60_Title", "TEXT", field_length=40)
    arcpy.management.CalculateField(
        h60_split_fc, "H60_Area",
        "'{:.2f}'.format(!H60Area!) if !H60Area! is not None else ''", "PYTHON3",
    )
    arcpy.management.CalculateField(
        h60_split_fc, "H60_Title",
        "str(!ELEVATION! or '') + ':' + str(!H60_Area! or '')", "PYTHON3",
    )

    # Parse above/below values
    h60_dict = {}
    with arcpy.da.SearchCursor(h60_split_fc, ["H60_Title"]) as cursor:
        for row in cursor:
            title = str(row[0])
            parts = title.split(":")
            if len(parts) < 2 or not parts[1].strip():
                continue
            if title.startswith("H60 A"):
                h60_dict["Above"] = parts[1]
            else:
                h60_dict["Below"] = parts[1]

    above_pct = float(h60_dict.get("Above", 0)) / basin_area * 100
    below_pct = float(h60_dict.get("Below", 0)) / basin_area * 100
    above = f"Total H60 Above {h60_dict.get('Above', '0')} ({above_pct:.1f})"
    below = f"Total H60 Below {h60_dict.get('Below', '0')} ({below_pct:.1f})"

    return h60_split_fc, above, below


def label_h60_split(h60_split_fc):
    """Add text label fields to an existing H60Split feature class.

    Adds H60_Area (TEXT) and H60_Title (TEXT) without re-deriving the
    H60 split geometry.  Used by the Final tool when copying H60Split
    from the Estimate GDB.
    """
    # Delete and re-add so field_length is always correct regardless of Estimate GDB version
    for fld in ("H60_Area", "H60_Title"):
        if fld in [f.name for f in arcpy.ListFields(h60_split_fc)]:
            arcpy.management.DeleteField(h60_split_fc, fld)
    arcpy.management.AddField(h60_split_fc, "H60_Area",  "TEXT", field_length=20)
    arcpy.management.AddField(h60_split_fc, "H60_Title", "TEXT", field_length=40)
    arcpy.management.CalculateField(
        h60_split_fc, "H60_Area",
        "'{:.2f}'.format(!H60Area!) if !H60Area! is not None else ''", "PYTHON3",
    )
    arcpy.management.CalculateField(
        h60_split_fc, "H60_Title",
        "(str(!ELEVATION!) if !ELEVATION! is not None else '') + ':' + "
        "(str(!H60_Area!) if !H60_Area! is not None else '')", "PYTHON3",
    )


def calc_aspect(dem, output_gdb, output_folder):
    """Create an aspect raster, reclassify to cardinal directions, write to output GDB."""
    arcpy.AddMessage("Creating Aspect raster")

    pre_aspect = "memory\\pre_aspect"
    mult_asp = "memory\\mult_aspect"
    aspect_poly = "memory\\aspectPoly"
    aspect_dissolve = "memory\\aspectDissolve"
    output_path = os.path.join(output_folder, "aspect")
    aspect_fc = gdb_fc(output_gdb, FC_ASPECT)

    out_aspect = Aspect(in_raster=dem)
    out_aspect.save(pre_aspect)

    # Multiply by 10 and truncate to integer for remap precision
    mult_aspect = arcpy.Raster(pre_aspect) * 10
    int_aspect = Int(mult_aspect)
    int_aspect.save(mult_asp)

    arcpy.management.BuildRasterAttributeTable(mult_asp)
    remap = RemapRange(ASPECT_REMAP)
    reclassed = Reclassify(mult_asp, "VALUE", remap)
    reclassed.save(output_path)

    arcpy.conversion.RasterToPolygon(reclassed, aspect_poly, "NO_SIMPLIFY")
    arcpy.management.Dissolve(aspect_poly, aspect_dissolve, "GRIDCODE")
    arcpy.management.CopyFeatures(aspect_dissolve, aspect_fc)

    # Add area field
    calc_area_hectares(aspect_fc, "Area")
    arcpy.management.Delete(output_path)


def calc_slope(dem, output_gdb, output_folder):
    """Create a slope % raster, reclassify to ranges, write to output GDB."""
    arcpy.AddMessage("Creating Slope raster")

    pre_slope = "memory\\pre_slope"
    slope_poly = "memory\\slopePoly"
    slope_dissolve = "memory\\slopeDissolve"
    output_path = os.path.join(output_folder, "slope")
    slope_fc = gdb_fc(output_gdb, FC_SLOPE)

    out_slope = Slope(in_raster=dem, output_measurement="PERCENT_RISE", z_unit="METER")
    int_slope = Int(out_slope)
    int_slope.save(pre_slope)

    arcpy.management.BuildRasterAttributeTable(pre_slope)
    remap = RemapRange(SLOPE_REMAP)
    reclassed = Reclassify(pre_slope, "VALUE", remap)
    reclassed.save(output_path)

    arcpy.conversion.RasterToPolygon(reclassed, slope_poly, "NO_SIMPLIFY", "VALUE")
    arcpy.management.Dissolve(slope_poly, slope_dissolve, "GRIDCODE")
    arcpy.management.CopyFeatures(slope_dissolve, slope_fc)

    # Add area field
    calc_area_hectares(slope_fc, "Area")
    arcpy.management.Delete(output_path)
