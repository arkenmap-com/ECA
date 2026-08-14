"""
Database connection management and spreadsheet-based layer configuration.

Reads the ECA_Input_Layers.xlsx spreadsheet to discover input layers,
validates the BCGW SDE connection and resolves full feature
class paths for use by the geoprocessing pipeline.
"""

import arcpy
import os
import pandas as pd


def load_layer_config(xlsx_path):
    """Read the layer configuration spreadsheet.

    Returns ``(vector_layers, dem_layers, joins)`` where each is a list of
    dicts with keys matching the spreadsheet column names.

    The optional "Joins" sheet defines table joins to apply before clipping.
    """
    vector_layers = (
        pd.read_excel(xlsx_path, sheet_name="Layers", engine="openpyxl")
        .where(pd.notnull, None)
        .to_dict("records")
    )
    dem_layers = (
        pd.read_excel(xlsx_path, sheet_name="DEMs", engine="openpyxl")
        .where(pd.notnull, None)
        .to_dict("records")
    )

    # Joins sheet is optional
    try:
        joins = (
            pd.read_excel(xlsx_path, sheet_name="Joins", engine="openpyxl")
            .where(pd.notnull, None)
            .to_dict("records")
        )
    except ValueError:
        # Sheet doesn't exist
        joins = []

    return vector_layers, dem_layers, joins


def check_db_connections():
    """Validate that required SDE connections exist before proceeding.

    Returns ``{"BCGW": path}``.  ArcGIS Pro will prompt
    the user to authenticate if they haven't already -- no extra tool
    parameters needed.
    """
    import sys

    bcgw_path = r'F:\south_root\GIS_Workspace\Scripts_and_Tools\BCGW.sde'
    if not arcpy.Exists(bcgw_path):
        arcpy.AddError(
            "Please make sure you have a connection to the BCGW.sde in your "
            "database connections and that it's connected before running tool"
        )
        sys.exit(1)
    bcgw = bcgw_path + '\\'

    arcpy.AddMessage("Database connections validated successfully.")
    return {"BCGW": bcgw}


def resolve_layer_path(row, connections):
    """Build a full arcpy-usable path from a spreadsheet row and connection dict.

    *row* must have keys ``Data_Source`` and ``Feature_Class``.
    """
    source = str(row["Data_Source"]).upper()
    fc = row["Feature_Class"]

    if source == "BCGW":
        return os.path.join(connections["BCGW"], fc)
    elif source == "LOCAL":
        return fc
    else:
        raise ValueError(
            f"Layer '{row.get('Layer_Name', fc)}' has unrecognized Data_Source "
            f"'{row['Data_Source']}'. Expected 'BCGW' or 'LOCAL'."
        )


def resolve_dem_path(dem_row, connections):
    """Build a full path for a DEM raster from the DEMs sheet."""
    source = str(dem_row["Data_Source"]).upper()
    raster = dem_row["Raster_Path"]

    if source == "BCGW":
        return os.path.join(connections["BCGW"], raster)
    elif source == "LOCAL":
        return raster
    else:
        raise ValueError(
            f"DEM '{dem_row.get('DEM_Name', raster)}' has unrecognized "
            f"Data_Source '{dem_row['Data_Source']}'."
        )


def validate_all_layers(vector_layers, dem_layers, connections):
    """Check that every layer in the config exists in its data source.

    Returns a list of error messages (empty means all good).
    """
    errors = []

    for row in vector_layers:
        try:
            path = resolve_layer_path(row, connections)
        except ValueError as e:
            errors.append(str(e))
            continue

        if not arcpy.Exists(path):
            errors.append(
                f"Layer '{row.get('Layer_Name', '')}' not found at: {path}"
            )

    for row in dem_layers:
        try:
            path = resolve_dem_path(row, connections)
        except ValueError as e:
            errors.append(str(e))
            continue

        if not arcpy.Exists(path):
            errors.append(
                f"DEM '{row.get('DEM_Name', '')}' not found at: {path}"
            )

    return errors


def get_layers_by_step(vector_layers, step):
    """Filter vector layer configs by Processing_Step value."""
    return [r for r in vector_layers if r.get("Processing_Step") == step]


def get_dem_by_condition(dem_layers, condition):
    """Return the first DEM config matching the given Use_Condition."""
    for row in dem_layers:
        if row.get("Use_Condition") == condition:
            return row
    return None


def build_info_field_map(vector_layers, scratch_gdb):
    """Build the Info field mapping dict dynamically from spreadsheet config.

    Returns a dict of ``{clip_layer_path: "!FieldName!"}`` for layers
    that have an Info_Field defined.
    """
    mapping = {}
    for row in vector_layers:
        info_field = row.get("Info_Field")
        short_name = row.get("Short_Name")
        if info_field and short_name:
            clip_name = f"Clip_{short_name}"
            fc_path = os.path.join(scratch_gdb, clip_name)
            mapping[fc_path] = f"!{info_field}!"
    return mapping


def get_joins_for_layer(joins, short_name):
    """Return all join definitions for a given layer Short_Name.

    Returns a list of join dicts (may be empty if no joins configured).
    """
    return [j for j in joins if j.get("Layer_Short_Name") == short_name]


def apply_joins(feature_layer, joins_for_layer, connections):
    """Apply AddJoin operations to a feature layer.

    *feature_layer*: name of an existing feature layer (from MakeFeatureLayer).
    *joins_for_layer*: list of join dicts from ``get_joins_for_layer()``.
    *connections*: dict from ``validate_connections()``.

    Each join dict must have:
      - Join_Table: feature class / table name in the SDE
      - Join_Data_Source: "BCGW" / "LOCAL"
      - Join_From_Field: field in the source layer to join on
      - Join_To_Field: field in the join table to join on
      - Join_Type (optional): "KEEP_ALL" (default) or "KEEP_COMMON"
    """
    for j in joins_for_layer:
        # Resolve the join table path
        join_source = str(j.get("Join_Data_Source", "")).upper()
        join_table = j["Join_Table"]

        if join_source == "BCGW":
            join_path = os.path.join(connections["BCGW"], join_table)
        elif join_source == "LOCAL":
            join_path = join_table
        else:
            arcpy.AddWarning(
                f"Join table '{join_table}' has unrecognized Data_Source "
                f"'{join_source}' — skipping join."
            )
            continue

        from_field = j["Join_From_Field"]
        to_field = j["Join_To_Field"]
        join_type = j.get("Join_Type", "KEEP_ALL")

        arcpy.AddMessage(f"  Joining {join_table} on {from_field} = {to_field}")
        arcpy.management.AddJoin(
            feature_layer, from_field,
            join_path, to_field,
            join_type,
        )
