"""
Opening layer assembly for the ECA Estimate tool.

Handles clipping transport and opening layers, buffering roads,
merging VRI/Results/FTA, processing LRM blocks, and building the
final consolidated Openings feature class in the output GDB.
"""

import arcpy
import os

from core.config import (
    FLD_OPENING_ID, FLD_CROWN_CLOSURE, FLD_PROJ_HEIGHT,
    FLD_ECA_SRC, FLD_ECA_SRC_ALT, FLD_ECA_CROWN, FLD_ECA_HEIGHT,
    FLD_INFO, FLD_OVERRIDE, FLD_HECTARES, FLD_CUTB_SEQ_NBR,
    CLIP_LAYERS_REMOVE, LOWER_PRIORITY_OPENINGS, LAYERS_WITH_ECA_SRC,
)
from core.workspace import (
    FC_ROADS_DRA, FC_OPENINGS, FC_PRIVATE_LAND, FC_HISTORICAL_WILDFIRE,
    gdb_fc, cleanup_memory,
)
from core.database import resolve_layer_path, get_joins_for_layer, apply_joins
from core.utils import (
    ez_append, get_feature_count, safe_add_field,
    calc_area_hectares, fix_field_name,
)
from core.erase_features import EraseFeatures


def resolve_def_query(raw_query):
    """Substitute CURRENT_TIMESTAMP with a literal date value.

    Oracle's CURRENT_TIMESTAMP may not be evaluated correctly by
    arcpy.management.SelectLayerByAttribute.  Replace it with a concrete
    TIMESTAMP literal computed in Python so the query is portable.
    """
    if raw_query and "CURRENT_TIMESTAMP" in raw_query:
        import datetime
        now = datetime.datetime.now()
        literal = f"TIMESTAMP '{now:%Y-%m-%d %H:%M:%S}'"
        resolved = raw_query.replace("CURRENT_TIMESTAMP", literal)
        arcpy.AddMessage(f"  Resolved query: {resolved}")
        return resolved
    return raw_query


def clip_transport_layers(layer_configs, connections, watershed, scratch_gdb, output_gdb,
                          joins=None):
    """Clip transportation layers to the watershed and return lists for buffering.

    *layer_configs*: spreadsheet rows filtered to transport_8 and transport_18.
    *connections*: dict from ``database.validate_connections()``.
    *joins*: list of join dicts from spreadsheet Joins sheet (optional).

    Returns ``[buffer_8_list, buffer_18_list]`` where each item is a list
    of clipped layer paths.
    """
    joins = joins or []
    buffer_8_list = []
    buffer_18_list = []

    for row in layer_configs:
        step = row.get("Processing_Step", "")
        short_name = row["Short_Name"]
        source_path = resolve_layer_path(row, connections)
        clip_name = f"Clip_{short_name}"
        clip_path = os.path.join(scratch_gdb, clip_name)
        def_query = resolve_def_query(row.get("Definition_Query"))

        arcpy.AddMessage(f"Clipping {row['Layer_Name']} layer ...")
        try:
            fl_name = f"fl_{clip_name}"
            arcpy.management.MakeFeatureLayer(source_path, fl_name)

            # Apply any joins defined in the Joins sheet
            layer_joins = get_joins_for_layer(joins, short_name)
            if layer_joins:
                apply_joins(fl_name, layer_joins, connections)

            # Filter by def_query then spatially select features in watershed
            if def_query:
                arcpy.AddMessage(f"  Definition query: {def_query}")
                arcpy.management.SelectLayerByAttribute(fl_name, "NEW_SELECTION", def_query)
                attr_count = get_feature_count(fl_name)
                arcpy.AddMessage(f"  After attribute selection: {attr_count} feature(s)")
                arcpy.management.SelectLayerByLocation(fl_name, "intersect", watershed, selection_type="SUBSET_SELECTION")
                spatial_count = get_feature_count(fl_name)
                arcpy.AddMessage(f"  After spatial selection: {spatial_count} feature(s)")
            else:
                arcpy.management.SelectLayerByLocation(fl_name, "intersect", watershed)
                spatial_count = get_feature_count(fl_name)
                arcpy.AddMessage(f"  After spatial selection: {spatial_count} feature(s)")

            # Clip selected features directly (no intermediate CopyFeatures)
            arcpy.analysis.Clip(fl_name, watershed, clip_path, "")
            arcpy.management.Delete(fl_name)

            if step == "transport_8":
                buffer_8_list.append(clip_path)
            elif step == "transport_18":
                buffer_18_list.append(clip_path)
        except Exception as e:
            arcpy.AddWarning(
                f"Could not clip {row['Layer_Name']} — skipping ({e})"
            )

    # Copy DRA roads to output GDB
    roads_dra_fc = gdb_fc(output_gdb, FC_ROADS_DRA)
    dra_layers = []
    for suffix in ("Clip_DRAMajor", "Clip_DRAMinor"):
        p = os.path.join(scratch_gdb, suffix)
        if arcpy.Exists(p):
            dra_layers.append(p)

    if dra_layers:
        if len(dra_layers) == 1:
            arcpy.management.CopyFeatures(dra_layers[0], roads_dra_fc)
        else:
            arcpy.management.Merge(dra_layers, roads_dra_fc)

    return [buffer_8_list, buffer_18_list]


def buffer_transport(list_list, scratch_gdb):
    """Create 8m (minor) and 18m (major) buffers around transport lines.

    Returns a list of buffer layer paths (excluding BCTS Proposed Roads)
    and the BCTS proposed roads buffer path separately.
    """
    buffer_distances = [4, 9]  # half-widths: 8m/2=4, 18m/2=9
    buffer_layers = []
    bcts_path = None

    for idx, layers in enumerate(list_list):
        dist = buffer_distances[idx]
        for layer_path in layers:
            layer_name = os.path.basename(layer_path)
            buff_name = f"buffer_{layer_name}"
            buff_path = os.path.join(scratch_gdb, buff_name)

            arcpy.AddMessage(f"Buffering {layer_name} at {dist * 2}m")
            arcpy.analysis.Buffer(layer_path, buff_path, dist, "FULL", "ROUND", "ALL")

            if "BCTSProposedRoads" in layer_name:
                bcts_path = buff_path
            else:
                buffer_layers.append(buff_path)

    return buffer_layers, bcts_path


def merge_transport(buffer_layers, watershed, scratch_gdb):
    """Merge and dissolve buffered transport layers.

    Creates Clip_RoadsPipelinesRailways in scratch_gdb.
    """
    if not buffer_layers:
        return

    merged = os.path.join(scratch_gdb, "merged_transport")
    dissolved = os.path.join(scratch_gdb, "dissolved_transport")
    clip_roads = os.path.join(scratch_gdb, "Clip_RoadsPipelinesRailways")

    if len(buffer_layers) == 1:
        arcpy.management.CopyFeatures(buffer_layers[0], merged)
    else:
        arcpy.management.Merge(buffer_layers, merged)

    arcpy.management.Dissolve(merged, dissolved)
    cleanup_memory(merged)
    arcpy.analysis.Clip(dissolved, watershed, clip_roads, "")
    cleanup_memory(dissolved)


def clip_opening_layers(layer_configs, connections, watershed, scratch_gdb, output_gdb,
                        joins=None):
    """Clip potential opening layers to the watershed.

    *layer_configs*: spreadsheet rows filtered to 'opening', 'other', and 'pest'.
    *joins*: list of join dicts from spreadsheet Joins sheet (optional).

    Returns a list of additional clip names that need to be appended to
    openings (those not in the remove list).
    """
    joins = joins or []
    layer_list = []

    for row in layer_configs:
        short_name = row["Short_Name"]
        source_path = resolve_layer_path(row, connections)
        clip_name = f"Clip_{short_name}"
        clip_path = os.path.join(scratch_gdb, clip_name)
        def_query = resolve_def_query(row.get("Definition_Query"))
        eca_source_label = row.get("ECA_Source_Label", row["Layer_Name"])

        arcpy.AddMessage(f"Clipping {row['Layer_Name']} layer ...")
        try:
            fl_name = f"fl_{clip_name}"
            arcpy.management.MakeFeatureLayer(source_path, fl_name)

            # Apply any joins defined in the Joins sheet
            layer_joins = get_joins_for_layer(joins, short_name)
            if layer_joins:
                apply_joins(fl_name, layer_joins, connections)

            # Filter by def_query then spatially select features in watershed
            if def_query:
                arcpy.AddMessage(f"  Definition query: {def_query}")
                arcpy.management.SelectLayerByAttribute(fl_name, "NEW_SELECTION", def_query)
                attr_count = get_feature_count(fl_name)
                arcpy.AddMessage(f"  After attribute selection: {attr_count} feature(s)")
                arcpy.management.SelectLayerByLocation(fl_name, "intersect", watershed, selection_type="SUBSET_SELECTION")
                spatial_count = get_feature_count(fl_name)
                arcpy.AddMessage(f"  After spatial selection: {spatial_count} feature(s)")
            else:
                arcpy.management.SelectLayerByLocation(fl_name, "intersect", watershed)
                spatial_count = get_feature_count(fl_name)
                arcpy.AddMessage(f"  After spatial selection: {spatial_count} feature(s)")

            # Clip selected features directly (no intermediate CopyFeatures)
            arcpy.analysis.Clip(fl_name, watershed, clip_path, "")
            arcpy.management.Delete(fl_name)
        except Exception as e:
            arcpy.AddWarning(
                f"Could not clip {row['Layer_Name']} — skipping ({e})"
            )
            continue

        # Add source tracking field
        if clip_name in LAYERS_WITH_ECA_SRC:
            safe_add_field(clip_path, FLD_ECA_SRC, "TEXT", field_length=50, alias="Source Layer")
            arcpy.management.CalculateField(
                clip_path, FLD_ECA_SRC, f'"{eca_source_label}"', "PYTHON3",
            )
        else:
            safe_add_field(clip_path, FLD_ECA_SRC_ALT, "TEXT", field_length=50, alias="Source Layer")
            arcpy.management.CalculateField(
                clip_path, FLD_ECA_SRC_ALT, f'"{eca_source_label}"', "PYTHON3",
            )

        if clip_name not in CLIP_LAYERS_REMOVE:
            layer_list.append(clip_name)

    # Copy private lands and wildfire to output GDB
    for name, fc_name in [("Clip_PrivateLands", FC_PRIVATE_LAND),
                           ("Clip_WildfireTwentyYearsPlus", FC_HISTORICAL_WILDFIRE)]:
        src = os.path.join(scratch_gdb, name)
        if arcpy.Exists(src):
            arcpy.management.CopyFeatures(src, gdb_fc(output_gdb, fc_name))

    return layer_list


def add_info_fields(scratch_gdb, layer_configs):
    """Create and populate the 'Info' field for report generation.

    Uses the Info_Field column from the spreadsheet config.
    """
    for row in layer_configs:
        info_field = row.get("Info_Field")
        short_name = row.get("Short_Name")
        if not info_field or not short_name:
            continue

        clip_name = f"Clip_{short_name}"
        fc = os.path.join(scratch_gdb, clip_name)
        if arcpy.Exists(fc):
            safe_add_field(fc, FLD_INFO, "TEXT", field_length=255, alias="Info")
            arcpy.management.CalculateField(fc, FLD_INFO, f"!{info_field}!", "PYTHON3")


def merge_vri_results_fta(scratch_gdb):
    """Merge VRI, Results, and FTA layers by OPENING_ID matching.

    For each Results/FTA record: if its OPENING_ID already exists in VRI,
    the VRI record is kept. Otherwise, the Results/FTA record is added
    (with its geometry erasing the overlapping VRI area).

    Writes the merged result to ``scratch_gdb/mergeFinal``.
    """
    vri = os.path.join(scratch_gdb, "Clip_VRIOpeningsandBurns")
    results = os.path.join(scratch_gdb, "Clip_Results")
    fta = os.path.join(scratch_gdb, "Clip_FTAPendingBlocks")
    merge_final = os.path.join(scratch_gdb, "mergeFinal")

    count = get_feature_count(vri)
    arcpy.AddMessage(f"Checking VRI Opening, Burns and Urban layer... {count} record(s) found")

    # Replace null OPENING_IDs in FTA
    if arcpy.Exists(fta):
        arcpy.management.SelectLayerByAttribute(fta, "", "OPENING_ID is null")
        arcpy.management.CalculateField(fta, FLD_OPENING_ID, "0", "PYTHON3")
        arcpy.management.SelectLayerByAttribute(fta, "CLEAR_SELECTION")

    current_layer = vri
    layers = [(results, "Results"), (fta, "FTA")]

    for layer_path, name in layers:
        if not arcpy.Exists(layer_path):
            arcpy.AddMessage(f"No {name} layer found, skipping")
            continue

        count = get_feature_count(layer_path)
        arcpy.AddMessage(f"Checking {name} layer... {count} record(s) found")

        # Add zero crown/height fields
        safe_add_field(layer_path, FLD_ECA_CROWN, "SHORT", alias="Crown Closure")
        arcpy.management.CalculateField(layer_path, FLD_ECA_CROWN, "0", "PYTHON3")
        safe_add_field(layer_path, FLD_ECA_HEIGHT, "SHORT", alias="Projected Height")
        arcpy.management.CalculateField(layer_path, FLD_ECA_HEIGHT, "0", "PYTHON3")

        if count == 0:
            arcpy.AddMessage("No records found")
            continue

        arcpy.AddMessage(f"Checking for matching OPENING_IDs between VRI and {name}")

        # Rename OPENING_ID to temp_ID to prevent conflicts during append
        safe_add_field(layer_path, "temp_ID", "LONG")
        arcpy.management.CalculateField(layer_path, "temp_ID", f"!{FLD_OPENING_ID}!", "PYTHON3")
        arcpy.management.DeleteField(layer_path, FLD_OPENING_ID)

        # Rename Info to inftmp
        safe_add_field(layer_path, "inftmp", "TEXT", field_length=255)
        arcpy.management.CalculateField(layer_path, "inftmp", f"!{FLD_INFO}!", "PYTHON3")
        arcpy.management.DeleteField(layer_path, FLD_INFO)

        # Get existing OPENING_IDs from VRI
        vri_ids = set(
            row[0] for row in arcpy.da.SearchCursor(current_layer, [FLD_OPENING_ID])
        )

        # Find non-matching IDs
        non_matching = []
        with arcpy.da.SearchCursor(layer_path, ["temp_ID"]) as cursor:
            for row in cursor:
                if row[0] not in vri_ids:
                    non_matching.append(row[0])

        arcpy.AddMessage(f"{len(non_matching)} non-matching record(s) found")

        if non_matching:
            ids_str = str(tuple(non_matching)) if len(non_matching) > 1 else f"({non_matching[0]})"
            query = f'"temp_ID" in {ids_str}'
            select_path = f"memory\\{name}_selected"
            merge_path = f"memory\\VRI_{name}"

            arcpy.analysis.Select(layer_path, select_path, query)

            # Erase VRI area under the new features
            erase = EraseFeatures(
                in_features=current_layer,
                erase_features=select_path,
                out_features=merge_path,
            )
            erase.erase_analysis()

            # Build field mappings for append
            fm = arcpy.FieldMappings()
            fm.addTable(merge_path)
            fm.addTable(select_path)

            vri_fields = [FLD_OPENING_ID, FLD_CROWN_CLOSURE, FLD_PROJ_HEIGHT, FLD_ECA_SRC, FLD_INFO]
            src_fields = ["temp_ID", FLD_ECA_CROWN, FLD_ECA_HEIGHT, FLD_ECA_SRC_ALT, "inftmp"]

            for vri_f, src_f in zip(vri_fields, src_fields):
                idx = fm.findFieldMapIndex(vri_f)
                if idx != -1:
                    field_map = fm.getFieldMap(idx)
                    field_map.addInputField(select_path, src_f)
                    fm.replaceFieldMap(idx, field_map)
                src_idx = fm.findFieldMapIndex(src_f)
                if src_idx != -1:
                    fm.removeFieldMap(src_idx)

            arcpy.management.Append(select_path, merge_path, "NO_TEST", fm)
            current_layer = merge_path

    # Clean up intermediate merge layers before final copy
    intermediates = [
        f"memory\\Results_selected", f"memory\\VRI_Results",
        f"memory\\FTA_selected", f"memory\\VRI_FTA",
    ]
    arcpy.management.CopyFeatures(current_layer, merge_final)
    cleanup_memory(intermediates)


def setup_lrm_blocks(scratch_gdb, layer_configs=None):
    """Process LRM blocks and standard units.

    For each block type (ADV, PP, Recent): if a block has corresponding
    productive SUs, use the SU geometries instead of the block geometry.
    Appends everything to a unified LRM_Blocks feature class, then erases
    from the existing mergeFinal openings.

    If *layer_configs* is provided, derives block/SU pairs from the
    Companion_Layer column.
    """
    merge_final = os.path.join(scratch_gdb, "mergeFinal")

    # Build block/SU pairs from spreadsheet or use defaults
    if layer_configs:
        block_su_pairs = []
        seen_pairs = set()
        for row in layer_configs:
            if row.get("Processing_Step") != "opening":
                continue

            short_name = row.get("Short_Name")
            if not short_name or not str(short_name).startswith("LRM"):
                continue

            companion = row.get("Companion_Layer")
            layer_name = str(row.get("Layer_Name", "")).upper()
            short_name_upper = str(short_name).upper()

            # Only treat true block rows as primary LRM sources.
            # SU-only rows can otherwise be appended twice (as block + companion flow).
            is_block_row = bool(companion) or ("BLOCK" in short_name_upper) or ("BLOCK" in layer_name)
            if not is_block_row:
                continue

            block_name = f"Clip_{short_name}"
            su_name = f"Clip_{companion}" if companion else None
            label = short_name
            pair = (block_name, su_name, label)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                block_su_pairs.append(pair)

        # Keep legacy behavior if no LRM rows were found in the spreadsheet.
        if not block_su_pairs:
            block_su_pairs = [
                ("Clip_LRMADVBlocks", "Clip_LRMADVPRODSU", "ADV"),
                ("Clip_LRMPPBlocks", "Clip_LRMPPPRODSU", "PP"),
                ("Clip_LRMBlocksRecent", "Clip_LRMPRODSURecent", "Recent"),
            ]
    else:
        block_su_pairs = [
            ("Clip_LRMADVBlocks", "Clip_LRMADVPRODSU", "ADV"),
            ("Clip_LRMPPBlocks", "Clip_LRMPPPRODSU", "PP"),
            ("Clip_LRMBlocksRecent", "Clip_LRMPRODSURecent", "Recent"),
        ]

    def _lrm_state_priority(text):
        """Return precedence rank for LRM states (lower is higher priority)."""
        value = str(text).upper()
        if "RECENT" in value:
            return 0
        if "ADV" in value:
            return 1
        if "PP" in value:
            return 2
        return 99

    # Ensure deterministic precedence regardless of spreadsheet row order.
    # Recent SU wins over ADV/PP, then ADV over PP.
    block_su_pairs.sort(key=lambda p: _lrm_state_priority(p[2]))

    # Track which CUTB_SEQ_NBR values were already satisfied by higher-priority SUs.
    su_ids_claimed = set()

    # Create LRM_Blocks from mergeFinal template
    arcpy.management.CreateFeatureclass(
        scratch_gdb, "LRM_Blocks", "POLYGON", merge_final,
    )
    lrm_blocks = os.path.join(scratch_gdb, "LRM_Blocks")

    arcpy.AddMessage(
        "Checking LRM Blocks & Standard Unit layers. "
        "If Block contains SUs, productive units are used; "
        "otherwise the entire cut block shape is used."
    )

    def append_lrm_non_overlapping(src_fc, tag):
        """Append src_fc to lrm_blocks after removing overlap with existing LRM."""
        if not arcpy.Exists(src_fc) or get_feature_count(src_fc) == 0:
            return

        if get_feature_count(lrm_blocks) == 0:
            ez_append(src_fc, lrm_blocks)
            return

        clean_fc = f"memory\\lrm_nonoverlap_{tag}"
        erase = EraseFeatures(
            in_features=src_fc,
            erase_features=lrm_blocks,
            out_features=clean_fc,
        )
        erase.erase_analysis()

        if arcpy.Exists(clean_fc) and get_feature_count(clean_fc) > 0:
            ez_append(clean_fc, lrm_blocks)
        cleanup_memory(clean_fc)

    for blocks_name, su_name, label in block_su_pairs:
        blocks_path = os.path.join(scratch_gdb, blocks_name)
        su_path = os.path.join(scratch_gdb, su_name) if su_name else None

        if not arcpy.Exists(blocks_path):
            continue

        # Create feature layers so selections persist between tool calls
        blocks_lyr = f"{blocks_name}_lyr"
        arcpy.management.MakeFeatureLayer(blocks_path, blocks_lyr)

        su_lyr = None
        if su_path and arcpy.Exists(su_path):
            su_lyr = f"{su_name}_lyr"
            arcpy.management.MakeFeatureLayer(su_path, su_lyr)

            # Fix ECAsrc field name
            fix_field_name(su_path, FLD_ECA_SRC_ALT, FLD_ECA_SRC, "TEXT", 50)

        block_count = get_feature_count(blocks_path)
        arcpy.AddMessage(f"{block_count} LRM {label} block(s) found.")

        if block_count > 0 and su_lyr is not None:
            block_ids = set(
                row[0] for row in arcpy.da.SearchCursor(blocks_path, [FLD_CUTB_SEQ_NBR])
            )
            su_ids = set(
                row[0] for row in arcpy.da.SearchCursor(su_path, [FLD_CUTB_SEQ_NBR])
            )
            raw_matching = (block_ids & su_ids)
            skipped_claimed = [cid for cid in raw_matching if cid in su_ids_claimed]
            matching = [cid for cid in raw_matching if cid not in su_ids_claimed]

            arcpy.AddMessage(
                f"{len(raw_matching)} raw matching {label} SU record(s) found by {FLD_CUTB_SEQ_NBR}."
            )
            if skipped_claimed:
                arcpy.AddMessage(
                    f"{len(skipped_claimed)} {label} SU record(s) skipped due to higher-priority SU state."
                )
            arcpy.AddMessage(f"{len(matching)} matching {label} SU record(s) selected after precedence.")

            if matching:
                ids_str = str(tuple(matching)) if len(matching) > 1 else f"({matching[0]})"
                query = f'"{FLD_CUTB_SEQ_NBR}" in {ids_str}'

                # Build CUTB_SEQ_NBR → Info lookup from matching blocks
                arcpy.management.SelectLayerByAttribute(blocks_lyr, "NEW_SELECTION", query)
                info_lookup = {
                    row[0]: row[1]
                    for row in arcpy.da.SearchCursor(blocks_lyr, [FLD_CUTB_SEQ_NBR, FLD_INFO])
                }

                # Propagate block Info onto SU records before appending
                safe_add_field(su_path, FLD_INFO, "TEXT", field_length=255, alias="Info")
                with arcpy.da.UpdateCursor(su_path, [FLD_CUTB_SEQ_NBR, FLD_INFO]) as cursor:
                    for row in cursor:
                        if row[0] in info_lookup:
                            row[1] = info_lookup[row[0]]
                            cursor.updateRow(row)

                # Append matching SUs using feature layer (selection persists)
                arcpy.management.SelectLayerByAttribute(su_lyr, "NEW_SELECTION", query)
                append_lrm_non_overlapping(su_lyr, f"{label}_su")
                arcpy.management.SelectLayerByAttribute(su_lyr, "CLEAR_SELECTION")

                # Prevent lower-priority SU states from reusing the same CUTB IDs.
                su_ids_claimed.update(matching)
                arcpy.AddMessage(
                    f"{len(su_ids_claimed)} CUTB_SEQ_NBR value(s) now claimed by SU precedence chain."
                )

                # Delete blocks that have SUs, keep remaining
                arcpy.management.SelectLayerByAttribute(blocks_lyr, "NEW_SELECTION", query)
                arcpy.management.DeleteFeatures(blocks_lyr)
                arcpy.management.SelectLayerByAttribute(blocks_lyr, "CLEAR_SELECTION")

        # Append remaining blocks
        if arcpy.Exists(blocks_path) and get_feature_count(blocks_path) > 0:
            append_lrm_non_overlapping(blocks_path, f"{label}_blocks")

    # Mark crown closure and height as 0
    arcpy.management.CalculateField(lrm_blocks, FLD_CROWN_CLOSURE, "0", "PYTHON3")
    arcpy.management.CalculateField(lrm_blocks, FLD_PROJ_HEIGHT, "0", "PYTHON3")

    # Erase LRM blocks area from existing openings
    merge_openings = os.path.join(scratch_gdb, "mergeOpenings")
    erase = EraseFeatures(
        in_features=merge_final,
        erase_features=lrm_blocks,
        out_features=merge_openings,
    )
    erase.erase_analysis()

    cleanup_memory(merge_final)

    # Fix any field name collisions
    fix_field_name(merge_openings, "CROWN_CLOSURE_1", FLD_CROWN_CLOSURE, "SHORT")
    fix_field_name(merge_openings, "PROJ_HEIGHT_12", FLD_PROJ_HEIGHT, "FLOAT")
    fix_field_name(merge_openings, FLD_ECA_SRC_ALT, FLD_ECA_SRC, "TEXT", 50)

    # Append LRM blocks
    ez_append(lrm_blocks, merge_openings)
    cleanup_memory(lrm_blocks)


def complete_openings(layer_list, scratch_gdb, output_gdb):
    """Append remaining layers to the openings and produce the Openings FC.

    *layer_list* are the additional clipped layer names (wildfire, etc.) that
    were not part of VRI/Results/FTA/LRM. The VRI/Results/FTA/LRM merge is
    the highest-priority base. Lower-priority configured layers are processed
    in LOWER_PRIORITY_OPENINGS order and are erased by the already-built
    openings before they are appended, preventing them from overwriting the
    higher-priority base or an earlier lower-priority layer.
    Writes Openings to *output_gdb*.
    """
    openings = os.path.join(scratch_gdb, "mergeOpenings")
    openings_fc = gdb_fc(output_gdb, FC_OPENINGS)

    priority_names = set(LOWER_PRIORITY_OPENINGS)
    ordered_layers = [
        name for name in LOWER_PRIORITY_OPENINGS if name in layer_list
    ]
    ordered_layers.extend(
        name for name in layer_list if name not in priority_names
    )

    for lyr_name in ordered_layers:
        lyr_path = os.path.join(scratch_gdb, lyr_name)
        if not arcpy.Exists(lyr_path):
            continue

        arcpy.AddMessage(f"Checking {lyr_name}")
        count = get_feature_count(lyr_path)
        if count == 0:
            arcpy.AddMessage("No records found")
            continue

        arcpy.AddMessage(f"{count} record(s) found")

        # Add zero crown/height
        safe_add_field(lyr_path, FLD_ECA_CROWN, "SHORT")
        arcpy.management.CalculateField(lyr_path, FLD_ECA_CROWN, "0", "PYTHON3")
        safe_add_field(lyr_path, FLD_ECA_HEIGHT, "FLOAT")
        arcpy.management.CalculateField(lyr_path, FLD_ECA_HEIGHT, "0", "PYTHON3")

        is_lower_priority = lyr_name in priority_names
        if is_lower_priority:
            # Preserve the higher-priority openings already assembled. Only
            # append the portion of this layer that is not already covered.
            append_path = os.path.join(scratch_gdb, f"pr_{lyr_name}")
            erase = EraseFeatures(
                in_features=lyr_path,
                erase_features=openings,
                out_features=append_path,
            )
            erase.erase_analysis()
            target_path = openings
        else:
            # Retain legacy behavior for any unclassified generic layer: the
            # incoming layer replaces overlap in the assembled openings.
            union_path = os.path.join(scratch_gdb, f"un_{lyr_name}")
            erase = EraseFeatures(
                in_features=openings,
                erase_features=lyr_path,
                out_features=union_path,
            )
            erase.erase_analysis()
            append_path = lyr_path
            target_path = union_path

            # Fix field names created by the Union-based erase.
            fix_field_name(target_path, FLD_ECA_SRC_ALT, FLD_ECA_SRC, "TEXT", 50)
            fix_field_name(target_path, "Info_1", FLD_INFO, "TEXT", 255)

        # Prepare layer fields for append
        fix_field_name(append_path, FLD_ECA_SRC, FLD_ECA_SRC_ALT, "TEXT", 50)
        if not any(f.name == FLD_INFO for f in arcpy.ListFields(append_path)):
            safe_add_field(append_path, FLD_INFO, "TEXT", field_length=255)
        safe_add_field(append_path, "inftmp", "TEXT", field_length=255)
        arcpy.management.CalculateField(append_path, "inftmp", f"!{FLD_INFO}!", "PYTHON3")
        arcpy.management.DeleteField(append_path, FLD_INFO)

        # Build field mappings and append
        fm = arcpy.FieldMappings()
        fm.addTable(target_path)
        fm.addTable(append_path)

        openings_fields = [FLD_CROWN_CLOSURE, FLD_PROJ_HEIGHT, FLD_ECA_SRC, FLD_INFO]
        layer_fields = [FLD_ECA_CROWN, FLD_ECA_HEIGHT, FLD_ECA_SRC_ALT, "inftmp"]

        for of, lf in zip(openings_fields, layer_fields):
            idx = fm.findFieldMapIndex(of)
            if idx != -1:
                field_map = fm.getFieldMap(idx)
                field_map.addInputField(append_path, lf)
                fm.replaceFieldMap(idx, field_map)

        arcpy.management.Append(append_path, target_path, "NO_TEST", fm)
        if is_lower_priority:
            cleanup_memory(append_path)
        else:
            cleanup_memory(openings)
            openings = target_path

    # Erase natural openings overlap
    nat_openings = os.path.join(scratch_gdb, "Clip_VRINaturalandOtherOpenings")
    if arcpy.Exists(nat_openings):
        openings_erased = "memory\\openingsErase"
        erase = EraseFeatures(
            in_features=openings,
            erase_features=nat_openings,
            out_features=openings_erased,
        )
        erase.erase_analysis()
        cleanup_memory(openings)
        openings = openings_erased

    arcpy.management.CopyFeatures(openings, openings_fc)
    cleanup_memory(openings)

    # Add Override field (for Final tool) and Hectares
    safe_add_field(openings_fc, FLD_OVERRIDE, "SHORT")
    arcpy.management.CalculateField(openings_fc, FLD_OVERRIDE, "-1", "PYTHON3")
    calc_area_hectares(openings_fc, FLD_HECTARES)
