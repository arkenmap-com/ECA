"""
Recovery curve calculation using Kim Green's BEC zone / field team curves.

Uses a direct UpdateCursor approach for efficient row-by-row calculation.
"""

import arcpy

from core.config import get_recovery_params


def calculate_recovery(height, crown_closure, params):
    """Apply the recovery curve to a single opening polygon.

    *params* is an 11-element tuple: ``(h0, h1, h2, h3, h4, h5, cc0, cc1, cc2, cc3, cc4)``

    Returns:
        int: recovery percentage (0-100), or a sentinel code:
            - 996 = BEC subzone not recognized
            - 997 = field team not recognized
            - 998 = BEC zone not applicable for field team
            - 999 = calculation error (should not happen)
    """
    # Sentinel checks
    if all(v == 0 for v in params):
        return 998
    if all(v == 1 for v in params):
        return 997
    if all(v == 2 for v in params):
        return 996

    h0, h1, h2, h3, h4, h5, cc0, cc1, cc2, cc3, cc4 = params
    h = height if height is not None else 0
    cc = crown_closure if crown_closure is not None else 0

    if h < h0:
        return 0
    elif h0 <= h < h1:
        if cc < cc0:
            return 0
        elif cc0 <= cc < cc1:
            return 10
        elif cc1 <= cc < cc2:
            return 20
        elif cc >= cc2:
            return 30
        else:
            return 999
    elif h1 <= h < h2:
        if cc < cc0:
            return 0
        elif cc0 <= cc < cc1:
            return 20
        elif cc1 <= cc < cc2:
            return 30
        elif cc >= cc2:
            return 50
        else:
            return 999
    elif h >= h2:
        if cc < cc0:
            return 0
        elif cc0 <= cc < cc1:
            return 30
        elif cc1 <= cc < cc2:
            return 50
        elif cc2 <= cc < cc3:
            return 70
        elif cc >= cc3:
            if h2 <= h < h3:
                return 80
            elif h3 <= h < h4:
                if cc3 <= cc < cc4:
                    return 80
                elif cc >= cc4:
                    return 90
                else:
                    return 999
            elif h4 <= h < h5:
                if cc3 <= cc < cc4:
                    return 90
                elif cc >= cc4:
                    return 100
                else:
                    return 999
            elif h >= h5:
                if cc >= cc3:
                    return 100
                else:
                    return 999
            else:
                return 999
        else:
            return 999
    else:
        return 999


def apply_recovery(openings_bec_path, has_override=False, curves=None):
    """Calculate recovery values for all rows in the Openings_BEC feature class.

    *openings_bec_path*: full path to the Openings_BEC feature class.

    If *curves* is provided (loaded via :func:`core.config.load_recovery_curves`),
    it is used instead of the hardcoded ``RECOVERY_CURVES`` dict.

    If *has_override* is True (Final tool), rows with Override != -1
    get their Override value instead of a curve calculation.
    """
    fields = ["Field_Team", "ZONE", "SUBZONE", "PROJ_HEIGHT_1", "CROWN_CLOSURE", "Recovery"]
    if has_override:
        fields.append("Override")

    with arcpy.da.UpdateCursor(openings_bec_path, fields) as cursor:
        for row in cursor:
            ft, zone, subzone, height, crown, recovery = row[:6]
            override = row[6] if has_override else -1

            if has_override and override is not None and override != -1:
                row[5] = override
            else:
                params = get_recovery_params(ft, zone, subzone, curves=curves)
                row[5] = calculate_recovery(height, crown, params)

            cursor.updateRow(row)


def check_and_fix_errors(openings_bec_path):
    """Check for recovery calculation errors and report counts.

    *openings_bec_path*: full path to the Openings_BEC feature class.

    Error codes:
        999 = Recovery curve code error
        998 = BEC zone not valid for field team
        997 = Field team not recognized
        996 = BEC subzone not recognized

    Replaces error codes with 0 and populates the Error field.
    """
    from core.utils import safe_add_field

    # Create a feature layer for selection operations
    lyr = "openings_bec_errors_lyr"
    arcpy.management.MakeFeatureLayer(openings_bec_path, lyr)

    safe_add_field(lyr, "Error", "TEXT")
    arcpy.management.CalculateField(lyr, "Error", '"None"', "PYTHON3")

    error_codes = {
        999: "Recovery Curve Code Error",
        998: "BEC Error",
        997: "Field Team Error",
        996: "BEC Sub-Zone Error",
    }

    total_errors = 0
    for code, message in error_codes.items():
        arcpy.management.SelectLayerByAttribute(
            lyr, "NEW_SELECTION", f'"Recovery" = {code}',
        )
        result = arcpy.management.GetCount(lyr)
        count = int(result.getOutput(0))
        total_errors += count
        arcpy.AddMessage(f"{count} {message}(s) found")

        if count > 0:
            arcpy.management.CalculateField(
                lyr, "Error", f'"{message}"', "PYTHON3",
            )
            arcpy.management.CalculateField(
                lyr, "Recovery", "0", "PYTHON3",
            )

    arcpy.management.SelectLayerByAttribute(lyr, "CLEAR_SELECTION")
    arcpy.AddMessage(f"{total_errors} Total Recovery Errors found")
    arcpy.management.Delete(lyr)
