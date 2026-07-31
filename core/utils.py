"""
Shared utility functions used across all ECA tools.
"""

import arcpy


def ez_append(input_fc, target_fc):
    """Append features using automatic field mapping (NO_TEST)."""
    field_mappings = arcpy.FieldMappings()
    field_mappings.addTable(target_fc)
    field_mappings.addTable(input_fc)
    arcpy.management.Append(input_fc, target_fc, "NO_TEST", field_mappings)


def get_feature_count(fc):
    """Return the integer feature count for a feature class or layer."""
    result = arcpy.management.GetCount(fc)
    return int(result.getOutput(0))


def safe_add_field(fc, field_name, field_type, field_length=None, alias=None):
    """Add a field only if it does not already exist."""
    existing = [f.name for f in arcpy.ListFields(fc)]
    if field_name not in existing:
        kwargs = {}
        if field_length is not None:
            kwargs["field_length"] = field_length
        if alias is not None:
            kwargs["field_alias"] = alias
        arcpy.management.AddField(fc, field_name, field_type, **kwargs)


def calc_area_hectares(fc, field_name="Hectares"):
    """Add (if needed) and populate a hectares field from shape geometry."""
    safe_add_field(fc, field_name, "FLOAT")
    arcpy.management.CalculateGeometryAttributes(
        fc, [[field_name, "AREA_GEODESIC"]], area_unit="HECTARES"
    )


def fix_field_name(fc, old_name, new_name, field_type="TEXT", field_length=50):
    """If *old_name* exists in *fc*, copy its values to *new_name* and delete *old_name*.

    This handles the common pattern where ESRI appends ``_1`` to field names
    during Union/Append operations (e.g. ``ECAsrc_1`` -> ``ECAsrc``).
    """
    existing = {f.name for f in arcpy.ListFields(fc)}
    if old_name in existing:
        safe_add_field(fc, new_name, field_type, field_length=field_length)
        arcpy.management.CalculateField(
            fc, new_name, f"!{old_name}!", "PYTHON3"
        )
        arcpy.management.DeleteField(fc, old_name)


def field_exists(fc, field_name):
    """Return True if *field_name* exists in *fc*."""
    return field_name in {f.name for f in arcpy.ListFields(fc)}


def build_field_mapping(target_fc, input_fc, target_fields, input_fields):
    """Build a FieldMappings object that maps *input_fields* -> *target_fields*.

    Both lists must be the same length.  Fields that already match by name
    are left as-is; mismatches are remapped.
    """
    fm = arcpy.FieldMappings()
    fm.addTable(target_fc)
    fm.addTable(input_fc)

    for target_name, input_name in zip(target_fields, input_fields):
        if target_name != input_name:
            idx = fm.findFieldMapIndex(target_name)
            if idx != -1:
                field_map = fm.getFieldMap(idx)
                field_map.addInputField(input_fc, input_name)
                fm.replaceFieldMap(idx, field_map)
            # Remove the input field's own mapping to avoid duplicates
            input_idx = fm.findFieldMapIndex(input_name)
            if input_idx != -1:
                fm.removeFieldMap(input_idx)

    return fm
