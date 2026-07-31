"""
Other openings, pest infestation, and spatial split operations.

Handles roads/natural/water/PAS opening layers, pest infestation,
and the H60/subbasin splitting used by both Estimate and Final tools.
"""

import arcpy
import os

from core.config import (
    FLD_ECA_SRC, FLD_ECA_SRC_ALT, FLD_HECTARES, FLD_BASIN_AREA,
    FLD_SUBBASIN_AREA, FLD_H60_AREA,
)
from core.workspace import (
    FC_OTHER_OPENINGS, FC_PEST_INFESTATION, FC_PRIVATE_LAND,
    FC_HISTORICAL_WILDFIRE, FC_BEC_ZONE, FC_OPENINGS_BEC,
    FC_OPENINGS_RECOVERY, FC_H60_BASIN, gdb_fc, cleanup_memory,
)
from core.database import resolve_layer_path
from core.utils import (
    ez_append, safe_add_field, calc_area_hectares, get_feature_count,
)
from core.erase_features import EraseFeatures


def create_other_openings(scratch_gdb, output_gdb):
    """Build the OtherOpenings FC from roads, natural openings, water, and PAS layers.

    Erases overlaps with the main Openings FC in priority order.
    Writes result to *output_gdb*/OtherOpenings.
    """
    clip_roads = os.path.join(scratch_gdb, "Clip_RoadsPipelinesRailways")
    clip_bcts = os.path.join(scratch_gdb, "buffer_Clip_BCTSProposedRoads")
    clip_nat = os.path.join(scratch_gdb, "Clip_VRINaturalandOtherOpenings")
    clip_water = os.path.join(scratch_gdb, "Clip_VRIWater")
    clip_pas = os.path.join(scratch_gdb, "Clip_ResultsPAS")
    openings_fc = gdb_fc(output_gdb, "Openings")
    other_openings_fc = gdb_fc(output_gdb, FC_OTHER_OPENINGS)

    # Erase BCTS roads from existing roads
    bcts_erased = os.path.join(scratch_gdb, "BCTSRoadsErased")
    if arcpy.Exists(clip_bcts) and arcpy.Exists(clip_roads):
        erase = EraseFeatures(clip_bcts, clip_roads, bcts_erased)
        erase.erase_analysis()

    # Collect processed layers, then Merge at end (avoids empty-FC append problem)
    parts = []
    fc_created = False

    def _add_to_other(source_path):
        """Add a processed layer to the OtherOpenings FC.
        First call creates the FC via CopyFeatures; subsequent calls use Append.
        """
        nonlocal fc_created
        if not fc_created:
            arcpy.management.CopyFeatures(source_path, other_openings_fc)
            fc_created = True
        else:
            ez_append(source_path, other_openings_fc)

    # --- Roads ---
    if arcpy.Exists(clip_roads):
        roads_erase1 = os.path.join(scratch_gdb, "roadsErase1")
        erase1 = EraseFeatures(clip_roads, openings_fc, roads_erase1)
        erase1.erase_analysis()
        safe_add_field(roads_erase1, FLD_ECA_SRC, "TEXT", field_length=50)
        arcpy.management.CalculateField(
            roads_erase1, FLD_ECA_SRC, '"Roads, Railways, Pipelines"', "PYTHON3",
        )
        _add_to_other(roads_erase1)
        cleanup_memory(roads_erase1)

    if arcpy.Exists(bcts_erased):
        roads_erase2 = os.path.join(scratch_gdb, "roadsErase2")
        erase2 = EraseFeatures(bcts_erased, openings_fc, roads_erase2)
        erase2.erase_analysis()
        cleanup_memory(bcts_erased)
        safe_add_field(roads_erase2, FLD_ECA_SRC, "TEXT", field_length=50)
        arcpy.management.CalculateField(
            roads_erase2, FLD_ECA_SRC, '"BCTS Proposed Roads"', "PYTHON3",
        )
        _add_to_other(roads_erase2)
        cleanup_memory(roads_erase2)

    # --- Natural openings ---
    if arcpy.Exists(clip_nat):
        if fc_created:
            nat_erase = os.path.join(scratch_gdb, "naturalOpeningsErase")
            erase_n = EraseFeatures(clip_nat, other_openings_fc, nat_erase)
            erase_n.erase_analysis()
        else:
            nat_erase = clip_nat  # nothing to erase from yet
        nat_erase1 = os.path.join(scratch_gdb, "naturalOpeningsErase1")
        erase_n = EraseFeatures(nat_erase, openings_fc, nat_erase1)
        erase_n.erase_analysis()
        if nat_erase != clip_nat:
            cleanup_memory(nat_erase)
        safe_add_field(nat_erase1, FLD_ECA_SRC, "TEXT", field_length=50)
        arcpy.management.CalculateField(
            nat_erase1, FLD_ECA_SRC, '"VRI Natural Openings"', "PYTHON3",
        )
        _add_to_other(nat_erase1)
        cleanup_memory(nat_erase1)

    # --- Water ---
    if arcpy.Exists(clip_water):
        if fc_created:
            water_erase = os.path.join(scratch_gdb, "waterErase")
            erase_w = EraseFeatures(clip_water, other_openings_fc, water_erase)
            erase_w.erase_analysis()
        else:
            water_erase = clip_water
        water_erase1 = os.path.join(scratch_gdb, "waterErase1")
        erase_w = EraseFeatures(water_erase, openings_fc, water_erase1)
        erase_w.erase_analysis()
        if water_erase != clip_water:
            cleanup_memory(water_erase)
        safe_add_field(water_erase1, FLD_ECA_SRC, "TEXT", field_length=50)
        arcpy.management.CalculateField(
            water_erase1, FLD_ECA_SRC, '"VRI Water"', "PYTHON3",
        )
        _add_to_other(water_erase1)
        cleanup_memory(water_erase1)

    # --- Results PAS ---
    if arcpy.Exists(clip_pas):
        if fc_created:
            pas_erase = os.path.join(scratch_gdb, "PASOpeningsErase")
            erase_p = EraseFeatures(clip_pas, other_openings_fc, pas_erase)
            erase_p.erase_analysis()
        else:
            pas_erase = clip_pas
        pas_erase1 = os.path.join(scratch_gdb, "PASOpeningsErase1")
        erase_p = EraseFeatures(pas_erase, openings_fc, pas_erase1)
        erase_p.erase_analysis()
        if pas_erase != clip_pas:
            cleanup_memory(pas_erase)
        safe_add_field(pas_erase1, FLD_ECA_SRC, "TEXT", field_length=50)
        arcpy.management.CalculateField(
            pas_erase1, FLD_ECA_SRC, '"Results PAS"', "PYTHON3",
        )
        _add_to_other(pas_erase1)
        cleanup_memory(pas_erase1)

    # If nothing was created (no layers existed), create an empty polygon FC
    if not fc_created:
        sr = arcpy.Describe(openings_fc).spatialReference
        arcpy.management.CreateFeatureclass(
            output_gdb, FC_OTHER_OPENINGS, "POLYGON",
            spatial_reference=sr,
        )


def create_pest_layer(scratch_gdb, output_gdb):
    """Build PestInfestation FC from current and historic pest data.

    Writes to *output_gdb*/PestInfestation.
    """
    clip_current = os.path.join(scratch_gdb, "Clip_CurrentPestInfestation")
    clip_historic = os.path.join(scratch_gdb, "Clip_HistoricPestInfestation")
    pest_fc = gdb_fc(output_gdb, FC_PEST_INFESTATION)
    openings_fc = gdb_fc(output_gdb, "Openings")

    # Use CopyFeatures for first layer, Append for second (avoids empty-FC problem)
    fc_created = False
    if arcpy.Exists(clip_current):
        arcpy.management.CopyFeatures(clip_current, pest_fc)
        fc_created = True
    if arcpy.Exists(clip_historic):
        if fc_created:
            ez_append(clip_historic, pest_fc)
        else:
            arcpy.management.CopyFeatures(clip_historic, pest_fc)
            fc_created = True

    # If neither exists, create empty FC
    if not fc_created:
        sr = arcpy.Describe(openings_fc).spatialReference
        arcpy.management.CreateFeatureclass(
            output_gdb, FC_PEST_INFESTATION, "POLYGON",
            spatial_reference=sr,
        )

    # Add ECAsrc field so reporting can read it
    safe_add_field(pest_fc, FLD_ECA_SRC, "TEXT", field_length=50)
    arcpy.management.CalculateField(
        pest_fc, FLD_ECA_SRC, '"Pest Infestation"', "PYTHON3",
    )


def split_by_h60(layer_names, layer_sources, h60_split_path):
    """Split layers by H60 Above/Below using intersection with H60Split.

    *layer_names*: list of layer/feature class names to split.
    *layer_sources*: dict mapping names to full paths.
    *h60_split_path*: full path to the H60Split feature class (required).

    Returns a dict of ``{name: h60_split_path}``.
    """
    results = {}
    for name in layer_names:
        source = layer_sources.get(name, name)

        arcpy.AddMessage(f"Splitting {name} by H60 Line")
        h60_path = f"memory\\{name}_H60"
        arcpy.analysis.Intersect([source, h60_split_path], h60_path, "NO_FID")
        results[name] = h60_path

    return results


def split_by_subbasin(h60_splits, basin_area, subbasins_path, output_gdb, scratch_gdb=None):
    """Split H60-split layers by subbasin and write to output GDB.

    *h60_splits*: dict from split_by_h60().
    *subbasins_path*: full path to the Sub_Basins FC in output GDB.
    *output_gdb*: path to the output geodatabase.
    """
    for name, h60_path in h60_splits.items():
        arcpy.AddMessage(f"Splitting {name}_H60 by Sub-Basin")

        # Truncate name to 10 chars for safe layer naming
        short = f"{name}_H60"[:10]
        if scratch_gdb:
            out_path = os.path.join(scratch_gdb, f"{short}_subbasin_Split")
        else:
            out_path = f"memory\\{short}_subbasin_Split"

        arcpy.analysis.Intersect([h60_path, subbasins_path], out_path, "NO_FID")

    # Clean up all H60 split intermediates (consumed by subbasin intersect)
    cleanup_memory(list(h60_splits.values()))

    # Write split results to output GDB feature classes
    _write_split("OtherOpeni_subbasin_Split", FC_OTHER_OPENINGS, output_gdb, scratch_gdb,
                  basin_area, hectares_field=FLD_HECTARES)
    _write_split("PestInfest_subbasin_Split", FC_PEST_INFESTATION, output_gdb, scratch_gdb,
                  basin_area, hectares_field="AREA_HA")
    _write_split("Clip_Priva_subbasin_Split", FC_PRIVATE_LAND, output_gdb, scratch_gdb,
                  basin_area, hectares_field=FLD_HECTARES)
    _write_split("Clip_Wildf_subbasin_Split", FC_HISTORICAL_WILDFIRE, output_gdb, scratch_gdb,
                  basin_area, hectares_field="HECTARES")


def _write_split(split_name, target_fc_name, output_gdb, scratch_gdb, basin_area, hectares_field):
    """Overwrite a target FC in the output GDB with split results and recalculate areas."""
    if scratch_gdb:
        split_path = os.path.join(scratch_gdb, split_name)
    else:
        split_path = f"memory\\{split_name}"

    if not arcpy.Exists(split_path):
        return

    target_fc = gdb_fc(output_gdb, target_fc_name)

    # Delete old FC and replace with split version
    if arcpy.Exists(target_fc):
        arcpy.management.Delete(target_fc)
    arcpy.management.CopyFeatures(split_path, target_fc)
    cleanup_memory(split_path)

    # Recalculate area fields
    calc_area_hectares(target_fc, hectares_field)
    safe_add_field(target_fc, FLD_BASIN_AREA, "FLOAT")
    arcpy.management.CalculateField(
        target_fc, FLD_BASIN_AREA, str(basin_area), "PYTHON3",
    )


def calc_subbasin_h60(output_gdb):
    """Calculate H60 percentages per subbasin using Union.

    Writes H60Basin to the output GDB.
    """
    h60_fc = gdb_fc(output_gdb, "H60Split")
    subbasins_fc = gdb_fc(output_gdb, "Sub_Basins")
    output_fc = gdb_fc(output_gdb, FC_H60_BASIN)

    arcpy.analysis.Union([h60_fc, subbasins_fc], output_fc, join_attributes="ALL")
    calc_area_hectares(output_fc, "H60BsnArea")
    safe_add_field(output_fc, "percent", "FLOAT")
    arcpy.management.CalculateField(
        output_fc, "percent", "!H60BsnArea! / !SubBasinArea! * 100", "PYTHON3",
    )

    # Clean up FID fields from Union
    for fld_name in [f.name for f in arcpy.ListFields(output_fc) if f.name.startswith("FID_")]:
        try:
            arcpy.management.DeleteField(output_fc, fld_name)
        except Exception:
            pass


def clip_bec_and_field_team(bec_path, field_team_path, watershed_path, output_gdb,
                             connections=None, bec_row=None, ft_row=None):
    """Clip BEC and Field Team layers to the watershed.

    Writes BEC_Zone to the output GDB.

    Parameters can be either:
    - Direct paths (*bec_path*, *field_team_path*), or
    - Spreadsheet rows (*bec_row*, *ft_row*) resolved via *connections*.
    """
    if bec_row and connections:
        bec_path = resolve_layer_path(bec_row, connections)
    if ft_row and connections:
        field_team_path = resolve_layer_path(ft_row, connections)

    layers = [
        ("BEC", bec_path, "Clip_BEC"),
        ("Field Team", field_team_path, "Clip_FieldTeam"),
    ]

    for name, source, clip_name in layers:
        clip_path = f"memory\\{clip_name}"
        select_path = f"memory\\select_{clip_name}"

        arcpy.AddMessage(f"Clipping {name} layer ...")

        fl_name = f"fl_{clip_name}"
        arcpy.management.MakeFeatureLayer(source, fl_name)
        arcpy.management.SelectLayerByLocation(fl_name, "intersect", watershed_path)
        arcpy.management.CopyFeatures(fl_name, select_path)
        arcpy.analysis.Clip(select_path, watershed_path, clip_path, "")
        arcpy.management.Delete(fl_name)

    # Write BEC to output GDB
    bec_zone_fc = gdb_fc(output_gdb, FC_BEC_ZONE)
    arcpy.management.CopyFeatures("memory\\Clip_BEC", bec_zone_fc)


def select_field_team(scratch_gdb=None):
    """Determine the dominant field team for the watershed.

    Returns the field team name string.
    """
    ft_layer = "memory\\Clip_FieldTeam"
    ft_dissolve = os.path.join(scratch_gdb, "ftDissolve") if scratch_gdb else "memory\\ftDissolve"

    arcpy.management.Dissolve(ft_layer, ft_dissolve, "FIELD_TEAM")
    calc_area_hectares(ft_dissolve, FLD_HECTARES)

    max_hectares = max(
        row[0] for row in arcpy.da.SearchCursor(ft_dissolve, [FLD_HECTARES])
    )
    arcpy.management.SelectLayerByAttribute(
        ft_dissolve, "", f"{FLD_HECTARES} = {max_hectares}",
    )

    ft_selected = "memory\\ftSelected"
    arcpy.management.CopyFeatures(ft_dissolve, ft_selected)

    field_team = None
    with arcpy.da.SearchCursor(ft_selected, ["FIELD_TEAM"]) as cursor:
        for row in cursor:
            field_team = row[0]

    arcpy.AddMessage(f"The majority of this watershed is in {field_team}")
    return field_team


def setup_curve_layer(field_team, output_gdb, scratch_gdb=None):
    """Intersect BEC zones with openings and add required fields.

    Writes Openings_BEC to the output GDB.
    Returns the path to the Openings_BEC feature class.
    """
    if scratch_gdb:
        openings_split = os.path.join(scratch_gdb, "Openings_H_subbasin_Split")
    else:
        openings_split = "memory\\Openings_H_subbasin_Split"

    clip_bec = "memory\\Clip_BEC"
    openings_bec_fc = gdb_fc(output_gdb, FC_OPENINGS_BEC)

    arcpy.AddMessage("Intersecting BEC zones with Openings")
    arcpy.analysis.Intersect([clip_bec, openings_split], openings_bec_fc, "NO_FID")
    cleanup_memory(openings_split)
    safe_add_field(openings_bec_fc, "Field_Team", "TEXT")
    arcpy.management.CalculateField(
        openings_bec_fc, "Field_Team", f'"{field_team}"', "PYTHON3",
    )
    calc_area_hectares(openings_bec_fc, FLD_HECTARES)
    safe_add_field(openings_bec_fc, "Recovery", "SHORT")

    return openings_bec_fc


def append_to_recovery_layer(openings_bec_path, basin_area, output_gdb):
    """Write final openings with recovery to the output GDB.

    Creates Openings_and_Recovery FC.
    """
    recovery_fc = gdb_fc(output_gdb, FC_OPENINGS_RECOVERY)

    arcpy.AddMessage("Creating final openings layer")
    arcpy.management.CopyFeatures(openings_bec_path, recovery_fc)
    safe_add_field(recovery_fc, FLD_BASIN_AREA, "FLOAT")
    arcpy.management.CalculateField(recovery_fc, FLD_BASIN_AREA, str(basin_area), "PYTHON3")
