"""
ECA Analysis Python Toolbox for ArcGIS Pro.

Contains two tools:
  1. ECA Estimate - Automated first-pass ECA analysis
  2. ECA Final    - Final ECA after manual review of openings

Spreadsheet-driven architecture: all input layers are defined in an
Excel configuration file. No APRX template required.

Authors: Eric Hoodicoff, Moez Labiadh (BCTS Kootenay Business Area)
Refactored for ArcGIS Pro: 2026
"""

import arcpy
import importlib
import os
import sys

# Ensure the toolbox directory is on the path so core modules can be imported
_TOOLBOX_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLBOX_DIR not in sys.path:
    sys.path.insert(0, _TOOLBOX_DIR)

# Import and hot-reload core modules so changes take effect without restarting Pro
import core.config
import core.utils
import core.erase_features
import core.database
import core.workspace
import core.watershed
import core.dem
import core.openings
import core.other_openings
import core.recovery
import core.reporting

def _reload_modules():
    """Reload all core modules for development hot-reload."""
    importlib.reload(core.config)
    importlib.reload(core.utils)
    importlib.reload(core.erase_features)
    importlib.reload(core.database)
    importlib.reload(core.workspace)
    importlib.reload(core.watershed)
    importlib.reload(core.dem)
    importlib.reload(core.openings)
    importlib.reload(core.other_openings)
    importlib.reload(core.recovery)
    importlib.reload(core.reporting)


class Toolbox:
    def __init__(self):
        self.label = "ECA Analysis Toolbox"
        self.alias = "ECA"
        self.tools = [ECAEstimateTool, ECAFinalTool, ECADashboardTool]


# ============================================================================
# Shared parameter builder
# ============================================================================

def _build_parameters():
    """Build the parameter set for the Estimate tool."""
    p_watershed = arcpy.Parameter(
        displayName="Input Watershed (Subbasins)",
        name="input_watershed",
        datatype="GPFeatureLayer",
        parameterType="Required",
        direction="Input",
    )
    p_watershed.filter.list = ["Polygon"]

    p_basin = arcpy.Parameter(
        displayName="Basin Name Field",
        name="basin_field",
        datatype="Field",
        parameterType="Required",
        direction="Input",
    )
    p_basin.parameterDependencies = [p_watershed.name]

    p_subbasin = arcpy.Parameter(
        displayName="Sub-Basin Name Field",
        name="subbasin_field",
        datatype="Field",
        parameterType="Required",
        direction="Input",
    )
    p_subbasin.parameterDependencies = [p_watershed.name]

    p_output = arcpy.Parameter(
        displayName="Output Folder",
        name="output_folder",
        datatype="DEFolder",
        parameterType="Required",
        direction="Input",
    )

    p_spreadsheet = arcpy.Parameter(
        displayName="Layer Configuration Spreadsheet",
        name="layer_config",
        datatype="DEFile",
        parameterType="Required",
        direction="Input",
    )
    p_spreadsheet.filter.list = ["xlsx"]
    p_spreadsheet.value = core.config.DEFAULT_SPREADSHEET

    p_recovery = arcpy.Parameter(
        displayName="Recovery Curves Spreadsheet",
        name="recovery_curves",
        datatype="DEFile",
        parameterType="Required",
        direction="Input",
    )
    p_recovery.filter.list = ["xlsx"]
    p_recovery.value = core.config.DEFAULT_RECOVERY_CURVES_XLSX

    return [p_watershed, p_basin, p_subbasin, p_output,
            p_spreadsheet, p_recovery]


def _build_final_parameters():
    """Build the parameter set for the Final tool."""
    p_estimate_gdb = arcpy.Parameter(
        displayName="Estimate Output GDB (with reviewed Openings)",
        name="estimate_gdb",
        datatype="DEWorkspace",
        parameterType="Required",
        direction="Input",
    )
    p_estimate_gdb.filter.list = ["Local Database"]

    p_output = arcpy.Parameter(
        displayName="Output Folder",
        name="output_folder",
        datatype="DEFolder",
        parameterType="Required",
        direction="Input",
    )

    p_recovery = arcpy.Parameter(
        displayName="Recovery Curves Spreadsheet",
        name="recovery_curves",
        datatype="DEFile",
        parameterType="Required",
        direction="Input",
    )
    p_recovery.filter.list = ["xlsx"]
    p_recovery.value = core.config.DEFAULT_RECOVERY_CURVES_XLSX

    return [p_estimate_gdb, p_output, p_recovery]


# ============================================================================
# Tool 1: ECA Estimate
# ============================================================================

class ECAEstimateTool:
    def __init__(self):
        self.label = "1 - ECA Estimate"
        self.description = (
            "Performs a quick automated Equivalent Clearcut Area analysis. "
            "A manual visual check should be performed afterwards to ensure "
            "openings and recovery values are correctly represented."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        return _build_parameters()

    def isLicensed(self):
        try:
            arcpy.CheckOutExtension("Spatial")
            return True
        except Exception:
            return False

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        _reload_modules()

        from core import config, database, workspace, watershed, dem
        from core import openings, other_openings, recovery, reporting

        arcpy.env.overwriteOutput = True
        arcpy.CheckOutExtension("Spatial")
        arcpy.env.workspace = "memory"

        input_ws = parameters[0].valueAsText
        basin_field = parameters[1].valueAsText
        subbasin_field = parameters[2].valueAsText
        output_folder = parameters[3].valueAsText
        xlsx_path = parameters[4].valueAsText
        recovery_xlsx = parameters[5].valueAsText

        # --- Load config and validate ---
        vector_layers, dem_layers, joins = database.load_layer_config(xlsx_path)
        recovery_curves = config.load_recovery_curves(recovery_xlsx)
        connections = database.check_db_connections()

        errors = database.validate_all_layers(vector_layers, dem_layers, connections)
        if errors:
            for e in errors:
                arcpy.AddError(e)
            raise arcpy.ExecuteError

        # --- Create workspaces ---
        output_gdb = workspace.create_output_gdb(output_folder, "estimate")
        scratch_gdb = "memory"
        outputs_dir = workspace.create_output_folders(output_folder, "estimate")
        output_paths = workspace.check_outputs("placeholder", outputs_dir, "estimate")

        # --- Watershed setup ---
        basin, basin_area = watershed.setup_watershed(input_ws, basin_field, output_gdb)
        # Re-check outputs with actual basin name
        output_paths = workspace.check_outputs(basin, outputs_dir, "estimate")
        watershed.setup_subbasins(input_ws, basin_field, subbasin_field, output_gdb)

        ws_fc = workspace.gdb_fc(output_gdb, workspace.FC_WATERSHED)
        subbasins_fc = workspace.gdb_fc(output_gdb, workspace.FC_SUBBASINS)

        # --- DEM and H60 ---
        us_border_row = database.get_layers_by_step(vector_layers, "reference")
        us_border_path = None
        for row in us_border_row:
            if row["Short_Name"] == "USCanadaBorder":
                us_border_path = database.resolve_layer_path(row, connections)
                break

        dem_condition = dem.check_border(ws_fc, us_border_path)
        dem_row = database.get_dem_by_condition(dem_layers, dem_condition)
        input_dem = database.resolve_dem_path(dem_row, connections)

        arcpy.AddMessage("Clipping DEM to the Watershed boundary")
        dem_path = dem.clip_dem(ws_fc, input_dem, output_folder)
        perc_40th = dem.calc_percentile(dem_path, output_folder)

        # Persist the watershed-clipped DEM for the Final tool
        arcpy.management.CopyRaster(
            dem_path,
            workspace.gdb_fc(output_gdb, workspace.RASTER_CLIPPED_DEM),
        )

        # Buffer watershed for smoother contour, re-clip DEM
        shed_buff = dem.buffer_watershed(ws_fc)
        arcpy.management.Delete(dem_path)
        dem_path = dem.clip_dem(shed_buff, input_dem, output_folder)

        dem.draw_contour_line(dem_path, perc_40th, ws_fc, output_gdb)
        dem.split_h60(ws_fc, dem_path, perc_40th, output_gdb, basin_area)

        h60_split_fc = workspace.gdb_fc(output_gdb, workspace.FC_H60_SPLIT)

        # --- Transport layers ---
        transport_configs = (
            database.get_layers_by_step(vector_layers, "transport_8")
            + database.get_layers_by_step(vector_layers, "transport_18")
        )
        list_list = openings.clip_transport_layers(
            transport_configs, connections, ws_fc, scratch_gdb, output_gdb, joins,
        )
        buff_layers, bcts_path = openings.buffer_transport(list_list, scratch_gdb)
        # Clean up transport clips — consumed by buffer_transport
        workspace.cleanup_memory(list_list[0], list_list[1])
        openings.merge_transport(buff_layers, ws_fc, scratch_gdb)
        # Clean up buffer layers — consumed by merge_transport (keep bcts for other_openings)
        workspace.cleanup_memory(buff_layers)

        # --- Opening layers ---
        opening_configs = (
            database.get_layers_by_step(vector_layers, "opening")
            + database.get_layers_by_step(vector_layers, "other")
            + database.get_layers_by_step(vector_layers, "pest")
        )
        layer_list = openings.clip_opening_layers(
            opening_configs, connections, ws_fc, scratch_gdb, output_gdb, joins,
        )
        openings.add_info_fields(scratch_gdb, opening_configs)
        openings.merge_vri_results_fta(scratch_gdb)
        openings.setup_lrm_blocks(scratch_gdb, vector_layers)
        openings.complete_openings(layer_list, scratch_gdb, output_gdb)

        # --- Other openings and pest ---
        other_openings.create_other_openings(scratch_gdb, output_gdb)
        other_openings.create_pest_layer(scratch_gdb, output_gdb)

        # --- BEC and Field Team ---
        bec_row = None
        ft_row = None
        for row in database.get_layers_by_step(vector_layers, "reference"):
            if row["Short_Name"] == "BEC":
                bec_row = row
            elif row["Short_Name"] == "FieldTeam":
                ft_row = row

        bec_path = database.resolve_layer_path(bec_row, connections) if bec_row else None
        ft_path = database.resolve_layer_path(ft_row, connections) if ft_row else None
        other_openings.clip_bec_and_field_team(bec_path, ft_path, ws_fc, output_gdb)
        ft = other_openings.select_field_team(scratch_gdb)
        workspace.save_metadata(output_gdb, ft, perc_40th)

        # --- H60 / subbasin splits ---
        openings_fc = workspace.gdb_fc(output_gdb, workspace.FC_OPENINGS)
        other_fc = workspace.gdb_fc(output_gdb, workspace.FC_OTHER_OPENINGS)
        pest_fc = workspace.gdb_fc(output_gdb, workspace.FC_PEST_INFESTATION)
        private_fc = workspace.gdb_fc(output_gdb, workspace.FC_PRIVATE_LAND)
        wildfire_fc = workspace.gdb_fc(output_gdb, workspace.FC_HISTORICAL_WILDFIRE)

        layer_sources = {
            "Openings": openings_fc,
            "OtherOpenings": other_fc,
            "PestInfestation": pest_fc,
            "Clip_PrivateLands": private_fc,
            "Clip_WildfireTwentyYearsPlus": wildfire_fc,
        }
        h60_splits = other_openings.split_by_h60(
            list(layer_sources.keys()), layer_sources, h60_split_fc,
        )
        other_openings.split_by_subbasin(
            h60_splits, basin_area, subbasins_fc, output_gdb, scratch_gdb,
        )
        other_openings.calc_subbasin_h60(output_gdb)

        # --- Recovery calculation ---
        openings_bec_fc = other_openings.setup_curve_layer(ft, output_gdb, scratch_gdb)
        recovery.apply_recovery(openings_bec_fc, has_override=False, curves=recovery_curves)
        recovery.check_and_fix_errors(openings_bec_fc)
        other_openings.append_to_recovery_layer(openings_bec_fc, basin_area, output_gdb)

        # --- Reports ---
        data = reporting.convert_feature_classes(output_gdb)
        openings_cols, other_cols, subbasin_cols = reporting.build_subbasin_sheets(data)
        reporting.build_summary_sheets(data, openings_cols, other_cols)
        reporting.export_reports(data, output_paths, basin_area, data.get("subbasins"))

        arcpy.AddMessage("ECA Estimate analysis complete")

    def postExecute(self, parameters):
        return


# ============================================================================
# Tool 2: ECA Final
# ============================================================================

class ECAFinalTool:
    def __init__(self):
        self.label = "2 - ECA Final"
        self.description = (
            "Performs the final ECA analysis after manual review. "
            "Run this after inspecting and adjusting the Openings "
            "(and optionally OtherOpenings) feature class in the "
            "Estimate output GDB."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        return _build_final_parameters()

    def isLicensed(self):
        try:
            arcpy.CheckOutExtension("Spatial")
            return True
        except Exception:
            return False

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        _reload_modules()

        from core import config, workspace, dem
        from core import other_openings, recovery, reporting

        arcpy.env.overwriteOutput = True
        arcpy.CheckOutExtension("Spatial")
        arcpy.env.workspace = "memory"

        estimate_gdb = parameters[0].valueAsText
        output_folder = parameters[1].valueAsText
        recovery_xlsx = parameters[2].valueAsText

        # --- Load recovery curves ---
        recovery_curves = config.load_recovery_curves(recovery_xlsx)

        # --- Read metadata from Estimate GDB ---
        field_team, perc_40th = workspace.read_metadata(estimate_gdb)
        arcpy.AddMessage(f"Field team: {field_team}, 40th percentile: {int(perc_40th)}")

        # --- Read basin name and area from Estimate GDB ---
        ws_fc_est = workspace.gdb_fc(estimate_gdb, workspace.FC_WATERSHED)
        with arcpy.da.SearchCursor(
            ws_fc_est, [config.FLD_WATERSHED, config.FLD_BASIN_AREA]
        ) as cursor:
            for row in cursor:
                basin, basin_area = row[0], row[1]

        # --- Create output workspaces ---
        output_gdb = workspace.create_output_gdb(output_folder, "final")
        outputs_dir = workspace.create_output_folders(output_folder, "final")
        output_paths = workspace.check_outputs(basin, outputs_dir, "final")

        # --- Copy reference layers from Estimate GDB ---
        for fc_name in [workspace.FC_WATERSHED, workspace.FC_SUBBASINS,
                        workspace.FC_H60_LINE, workspace.FC_H60_SPLIT,
                        workspace.FC_BEC_ZONE]:
            src = workspace.gdb_fc(estimate_gdb, fc_name)
            dst = workspace.gdb_fc(output_gdb, fc_name)
            arcpy.management.CopyFeatures(src, dst)
            arcpy.AddMessage(f"Copied {fc_name} from Estimate GDB")

        subbasins_fc = workspace.gdb_fc(output_gdb, workspace.FC_SUBBASINS)
        h60_split_fc = workspace.gdb_fc(output_gdb, workspace.FC_H60_SPLIT)

        # --- Add H60 text labels to copied H60Split ---
        dem.label_h60_split(h60_split_fc)

        # --- Aspect and slope from saved DEM ---
        clipped_dem = workspace.gdb_fc(
            estimate_gdb, workspace.RASTER_CLIPPED_DEM,
        )
        dem.calc_aspect(clipped_dem, output_gdb, output_folder)
        dem.calc_slope(clipped_dem, output_gdb, output_folder)

        # --- Import edited layers from Estimate GDB ---
        layer_sources = {}
        for fc_name in [workspace.FC_OPENINGS, workspace.FC_OTHER_OPENINGS,
                        workspace.FC_PEST_INFESTATION, workspace.FC_PRIVATE_LAND,
                        workspace.FC_HISTORICAL_WILDFIRE]:
            src = workspace.gdb_fc(estimate_gdb, fc_name)
            if arcpy.Exists(src):
                layer_sources[fc_name] = src
            else:
                arcpy.AddWarning(f"{fc_name} not found in Estimate GDB — skipped")

        # --- H60 / subbasin splits on edited data ---
        h60_splits = other_openings.split_by_h60(
            list(layer_sources.keys()), layer_sources, h60_split_fc,
        )
        other_openings.split_by_subbasin(
            h60_splits, basin_area, subbasins_fc, output_gdb,
        )
        other_openings.calc_subbasin_h60(output_gdb)

        # --- Recovery calculation (with override support) ---
        # setup_curve_layer expects Clip_BEC in memory
        bec_zone_fc = workspace.gdb_fc(output_gdb, workspace.FC_BEC_ZONE)
        arcpy.management.CopyFeatures(bec_zone_fc, "memory\\Clip_BEC")

        openings_bec_fc = other_openings.setup_curve_layer(field_team, output_gdb)
        recovery.apply_recovery(openings_bec_fc, has_override=True, curves=recovery_curves)
        recovery.check_and_fix_errors(openings_bec_fc)
        other_openings.append_to_recovery_layer(openings_bec_fc, basin_area, output_gdb)

        # --- Reports ---
        data = reporting.convert_feature_classes(output_gdb)
        openings_cols, other_cols, subbasin_cols = reporting.build_subbasin_sheets(data)
        reporting.build_summary_sheets(data, openings_cols, other_cols)
        reporting.export_reports(data, output_paths, basin_area, data.get("subbasins"))

        arcpy.AddMessage("ECA Final analysis complete")

    def postExecute(self, parameters):
        return


class ECADashboardTool:
    def __init__(self):
        self.label = "3 - ECA Dashboard"
        self.description = (
            "Exports an HTML dashboard from a completed ECA Final GDB. "
            "Run after the Final tool has finished successfully."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        p_gdb = arcpy.Parameter(
            displayName="Final Output GDB",
            name="final_gdb",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        p_gdb.filter.list = ["Local Database"]
        return [p_gdb]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        _reload_modules()
        from core import config, workspace, reporting
        from datetime import date

        arcpy.env.overwriteOutput = True

        final_gdb = parameters[0].valueAsText

        # Read basin name and area from Final GDB
        ws_fc = workspace.gdb_fc(final_gdb, workspace.FC_WATERSHED)
        with arcpy.da.SearchCursor(
            ws_fc, [config.FLD_WATERSHED, config.FLD_BASIN_AREA]
        ) as cursor:
            for row in cursor:
                basin, basin_area = row[0], row[1]

        year = date.today().year
        html_path = os.path.join(
            os.path.dirname(final_gdb),
            f"{basin}_{year}_FinalECA_Dashboard.html",
        )

        data = reporting.convert_feature_classes(final_gdb)
        openings_cols, other_cols, _ = reporting.build_subbasin_sheets(data)
        reporting.build_summary_sheets(data, openings_cols, other_cols)
        reporting.export_html_dashboard(final_gdb, html_path, data, basin, basin_area)

        arcpy.AddMessage(f"Dashboard saved: {html_path}")

    def postExecute(self, parameters):
        return
