"""
Watershed and sub-basin setup operations.

Handles dissolving input watersheds, creating subbasin layers,
and writing results to the output GDB.
"""

import arcpy
import os

from core.config import (
    FLD_WATERSHED, FLD_SUB_BASIN, FLD_BASIN_AREA, FLD_SUBBASIN_AREA,
)
from core.workspace import FC_WATERSHED, FC_SUBBASINS, gdb_fc
from core.utils import get_feature_count, calc_area_hectares


def setup_watershed(input_watershed, basin_field, output_gdb):
    """Dissolve subbasins into a single watershed boundary.

    Writes the dissolved polygon to *output_gdb*/Watershed_Boundary.
    Returns ``(basin_name, basin_area_ha)``.
    """
    dissolve_output = "memory\\subDis"
    watershed_fc = gdb_fc(output_gdb, FC_WATERSHED)

    arcpy.AddMessage("Creating Watershed Boundary Layer")
    arcpy.management.Dissolve(input_watershed, dissolve_output, basin_field)

    count = get_feature_count(dissolve_output)
    if count == 0:
        arcpy.AddError(
            "The dissolved watershed has no features. "
            "Please check your input watershed and basin field."
        )
        raise arcpy.ExecuteError

    if count > 1:
        arcpy.AddError(
            "You can only do one watershed at a time. "
            "The watershed field contains more than one watershed. "
            "Please correct and try again."
        )
        raise arcpy.ExecuteError

    # Get basin name
    basin = None
    with arcpy.da.SearchCursor(dissolve_output, [basin_field]) as cursor:
        for row in cursor:
            basin = row[0]

    # Copy to output GDB and add standard fields
    arcpy.management.CopyFeatures(dissolve_output, watershed_fc)

    # Rename the basin field to the standard name if different
    existing = {f.name for f in arcpy.ListFields(watershed_fc)}
    if basin_field != FLD_WATERSHED:
        if basin_field in existing:
            arcpy.management.AlterField(
                watershed_fc, basin_field, FLD_WATERSHED, FLD_WATERSHED,
            )

    # Add and calculate basin area
    calc_area_hectares(watershed_fc, FLD_BASIN_AREA)

    basin_area = max(
        row[0] for row in arcpy.da.SearchCursor(watershed_fc, [FLD_BASIN_AREA])
    )

    return basin, basin_area


def setup_subbasins(input_watershed, basin_field, subbasin_field, output_gdb):
    """Copy input subbasins to the output GDB as Sub_Basins.

    Standardises field names to Watershed / Sub_Basin / SubBasinArea.
    """
    subbasin_fc = gdb_fc(output_gdb, FC_SUBBASINS)

    arcpy.AddMessage("Creating Subbasins Layer")
    arcpy.management.CopyFeatures(input_watershed, subbasin_fc)

    if not arcpy.Exists(subbasin_fc):
        arcpy.AddError(
            f"Failed to create {subbasin_fc}. "
            "If the output GDB is open in ArcGIS Pro, close it and try again."
        )
        raise arcpy.ExecuteError

    existing = {f.name for f in arcpy.ListFields(subbasin_fc)}

    # Rename basin field
    if basin_field != FLD_WATERSHED and basin_field in existing:
        arcpy.management.AlterField(
            subbasin_fc, basin_field, FLD_WATERSHED, FLD_WATERSHED,
        )

    # Rename subbasin field
    if subbasin_field != FLD_SUB_BASIN and subbasin_field in existing:
        # Avoid conflict if basin_field was just renamed
        if subbasin_field != basin_field:
            arcpy.management.AlterField(
                subbasin_fc, subbasin_field, FLD_SUB_BASIN, FLD_SUB_BASIN,
            )

    # If basin == subbasin field, copy watershed name to sub-basin
    if basin_field == subbasin_field:
        if FLD_SUB_BASIN not in {f.name for f in arcpy.ListFields(subbasin_fc)}:
            arcpy.management.AddField(subbasin_fc, FLD_SUB_BASIN, "TEXT", field_length=100)
        arcpy.management.CalculateField(
            subbasin_fc, FLD_SUB_BASIN, f"!{FLD_WATERSHED}!", "PYTHON3",
        )

    # Default blank/null Sub_Basin values to the watershed name
    with arcpy.da.UpdateCursor(subbasin_fc, [FLD_SUB_BASIN, FLD_WATERSHED]) as cursor:
        for row in cursor:
            if not row[0] or (isinstance(row[0], str) and row[0].strip() == ""):
                row[0] = row[1]
                cursor.updateRow(row)

    # Add and calculate subbasin area
    calc_area_hectares(subbasin_fc, FLD_SUBBASIN_AREA)
