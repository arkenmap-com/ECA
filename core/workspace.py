"""
Output workspace management for the ECA Toolbox.

Handles creation of the output GDB, report directories, in-memory
workspace cleanup, and path-building helpers. Intermediate feature
classes use the ``memory`` workspace for performance; final outputs
are written to the output file GDB.
"""

import arcpy
import os
from shutil import copy as copy_file

from core.config import ASSUMPTIONS_PDF, INSTRUCTIONS_PDF


# ---------------------------------------------------------------------------
# Output GDB feature class names
# ---------------------------------------------------------------------------
FC_WATERSHED = "Watershed_Boundary"
FC_SUBBASINS = "Sub_Basins"
FC_H60_LINE = "H60_Line"
FC_H60_SPLIT = "H60Split"
FC_H60_BASIN = "H60Basin"
FC_OPENINGS = "Openings"
FC_OPENINGS_BEC = "Openings_BEC"
FC_OPENINGS_RECOVERY = "Openings_and_Recovery"
FC_OTHER_OPENINGS = "OtherOpenings"
FC_PEST_INFESTATION = "PestInfestation"
FC_ROADS_DRA = "Roads_DRA"
FC_BEC_ZONE = "BEC_Zone"
FC_PRIVATE_LAND = "Clip_PrivateLands"
FC_HISTORICAL_WILDFIRE = "Clip_WildfireTwentyYearsPlus"
FC_ASPECT = "Aspect"
FC_SLOPE = "Slope"

METADATA_TABLE = "ECA_Metadata"
RASTER_CLIPPED_DEM = "Clipped_DEM"


def create_output_gdb(output_folder, tool_type="estimate"):
    """Create the output file geodatabase.

    Returns the full path to the GDB.
    """
    gdb_names = {
        "estimate": "ECA_Estimate.gdb",
        "final": "ECA_Final.gdb",
    }
    gdb_name = gdb_names.get(tool_type, "ECA_Estimate.gdb")
    gdb_path = os.path.join(output_folder, gdb_name)

    if arcpy.Exists(gdb_path):
        arcpy.AddError(
            f"Output GDB already exists: {gdb_path}\n"
            "Please delete it or choose a different output folder."
        )
        raise arcpy.ExecuteError

    arcpy.management.CreateFileGDB(output_folder, gdb_name.replace(".gdb", ""))
    arcpy.AddMessage(f"Created output GDB: {gdb_path}")
    return gdb_path


def cleanup_memory(*paths):
    """Delete in-memory feature classes that are no longer needed.

    Accepts any number of path strings or lists of paths.
    Silently skips paths that do not exist.
    """
    for item in paths:
        targets = item if isinstance(item, (list, tuple)) else [item]
        for path in targets:
            if path and arcpy.Exists(path):
                try:
                    arcpy.management.Delete(path)
                except Exception:
                    pass


def create_output_folders(output_folder, tool_type="estimate"):
    """Create the report output directory and copy documentation PDFs.

    Returns the outputs directory path.
    """
    folder_names = {
        "estimate": "EstimateOutputs",
        "final": "Final_Outputs",
    }
    folder_name = folder_names.get(tool_type, "EstimateOutputs")
    outputs_dir = os.path.join(output_folder, folder_name)
    os.makedirs(outputs_dir, exist_ok=True)

    # Copy documentation
    _copy_docs(outputs_dir, include_instructions=(tool_type == "estimate"))

    return outputs_dir


def _copy_docs(outputs_dir, include_instructions=True):
    """Copy assumption (and optionally instruction) PDFs to the output folder."""
    try:
        copy_file(ASSUMPTIONS_PDF, os.path.join(outputs_dir, "ECAToolAssumptions.pdf"))
    except (OSError, FileNotFoundError):
        arcpy.AddWarning(f"Could not copy assumptions PDF from {ASSUMPTIONS_PDF}")

    if include_instructions:
        try:
            copy_file(INSTRUCTIONS_PDF, os.path.join(outputs_dir, "ECAToolInstructions.pdf"))
        except (OSError, FileNotFoundError):
            arcpy.AddWarning(f"Could not copy instructions PDF from {INSTRUCTIONS_PDF}")


def gdb_fc(gdb_path, fc_name):
    """Return the full path to a feature class inside a geodatabase."""
    return os.path.join(gdb_path, fc_name)


def cleanup_scratch(scratch_gdb):
    """Delete the scratch geodatabase (legacy file-GDB cleanup).

    Kept for backward compatibility but no longer called by the main
    toolbox, which now uses the in-memory workspace instead.
    """
    if scratch_gdb == "memory":
        return
    if arcpy.Exists(scratch_gdb):
        try:
            arcpy.management.Delete(scratch_gdb)
            arcpy.AddMessage("Scratch geodatabase deleted.")
        except Exception:
            arcpy.AddWarning(
                f"Could not delete scratch GDB: {scratch_gdb}\n"
                "You can delete it manually."
            )


def check_outputs(basin, outputs_dir, tool_type="estimate"):
    """Verify that output report files do not already exist.

    Returns a dict of output paths keyed by name.
    Raises arcpy.ExecuteError if any output already exists.
    """
    from datetime import date
    year = date.today().year
    prefix_map = {
        "estimate": "EstimateECA",
        "final": "FinalECA",
    }
    prefix = prefix_map.get(tool_type, "EstimateECA")

    paths = {
        "xlsx_openings": f"{basin}_{year}_{prefix}_Report.xlsx",
        "xlsx_other":    f"{basin}_{year}_OtherOpenings_Report.xlsx",
        "xlsx_pest":     f"{basin}_{year}_PestInfestation_Report.xlsx",
    }

    result = {}
    for key, filename in paths.items():
        full_path = os.path.join(outputs_dir, filename)
        if os.path.exists(full_path):
            arcpy.AddError(
                f"{filename} ALREADY EXISTS\n"
                "Please delete the file or choose a different output folder."
            )
            raise arcpy.ExecuteError
        result[key] = full_path

    return result


def save_metadata(gdb, field_team, percentile):
    """Save analysis metadata to a table in the output GDB.

    Creates a single-row table with the field team name and 40th
    percentile elevation value so the Final tool can reuse them.
    """
    table_path = os.path.join(gdb, METADATA_TABLE)
    arcpy.management.CreateTable(gdb, METADATA_TABLE)
    arcpy.management.AddField(table_path, "Field_Team", "TEXT", field_length=50)
    arcpy.management.AddField(table_path, "Percentile_40th", "DOUBLE")
    with arcpy.da.InsertCursor(table_path, ["Field_Team", "Percentile_40th"]) as cursor:
        cursor.insertRow([field_team, percentile])
    arcpy.AddMessage(f"Saved metadata: field_team={field_team}, percentile={percentile}")


def read_metadata(gdb):
    """Read analysis metadata from an Estimate output GDB.

    Returns ``(field_team, percentile_40th)`` tuple.
    Raises ``arcpy.ExecuteError`` if the metadata table is missing.
    """
    table_path = os.path.join(gdb, METADATA_TABLE)
    if not arcpy.Exists(table_path):
        arcpy.AddError(
            f"Metadata table not found in {gdb}.\n"
            "Please re-run the Estimate tool to generate the required metadata."
        )
        raise arcpy.ExecuteError

    with arcpy.da.SearchCursor(table_path, ["Field_Team", "Percentile_40th"]) as cursor:
        for row in cursor:
            return row[0], row[1]

    arcpy.AddError("Metadata table is empty.")
    raise arcpy.ExecuteError
