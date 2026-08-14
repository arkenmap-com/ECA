"""
Centralized configuration for the ECA Toolbox.

All hardcoded paths, field names, and recovery curve data
are defined here so they can be maintained in one place.
"""

import math
import os

# ---------------------------------------------------------------------------
# Network / base paths  (override these if your network layout differs)
# ---------------------------------------------------------------------------
BASE_NETWORK_PATH = r"\\bctsdata.bcgov\data\tko_root\GIS_Workspace"
TOOLS_PATH = os.path.join(BASE_NETWORK_PATH, "Tools", "ECA")
DOCUMENTATION_PATH = os.path.join(TOOLS_PATH, "Documentation")
ASSUMPTIONS_PDF = os.path.join(DOCUMENTATION_PATH, "ECAToolAssumptions.pdf")
INSTRUCTIONS_PDF = os.path.join(DOCUMENTATION_PATH, "ECAToolInstructions.pdf")

# ---------------------------------------------------------------------------
# Template paths
# ---------------------------------------------------------------------------
TOOLBOX_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(TOOLBOX_DIR, "templates")
DEFAULT_SPREADSHEET = os.path.join(TEMPLATES_DIR, "TKO_ECA_Input_Layers.xlsx")
DEFAULT_RECOVERY_CURVES_XLSX = os.path.join(TEMPLATES_DIR, "TKO_ECA_Recovery_Curves.xlsx")

# ---------------------------------------------------------------------------
# Field name constants
# ---------------------------------------------------------------------------
FLD_WATERSHED = "Watershed"
FLD_SUB_BASIN = "Sub_Basin"
FLD_BASIN_AREA = "BasinArea"
FLD_SUBBASIN_AREA = "SubBasinArea"
FLD_HECTARES = "Hectares"
FLD_CROWN_CLOSURE = "CROWN_CLOSURE"
FLD_PROJ_HEIGHT = "PROJ_HEIGHT_1"
FLD_OPENING_ID = "OPENING_ID"
FLD_ECA_SRC = "ECAsrc"
FLD_ECA_SRC_ALT = "ECAsrc_1"
FLD_ECA_CROWN = "ECAcrown"
FLD_ECA_HEIGHT = "ECAheight"
FLD_RECOVERY = "Recovery"
FLD_OVERRIDE = "Override"
FLD_ERROR = "Error"
FLD_INFO = "Info"
FLD_FIELD_TEAM = "Field_Team"
FLD_ELEVATION = "ELEVATION"
FLD_H60_AREA = "H60Area"
FLD_CUTB_SEQ_NBR = "CUTB_SEQ_NBR"

# ---------------------------------------------------------------------------
# Clipped layer short-name sets used in the processing pipeline
#
# These use the Short_Name from the spreadsheet, prefixed with "Clip_".
# ---------------------------------------------------------------------------
CLIP_LAYERS_REMOVE = [
    "Clip_VRIOpeningsandBurns", "Clip_Results", "Clip_FTAPendingBlocks",
    "Clip_CurrentPestInfestation", "Clip_HistoricPestInfestation",
    "Clip_VRINaturalandOtherOpenings", "Clip_ResultsPAS",
    # VRI Water is assembled by create_other_openings(), not the main
    # Openings precedence chain.
    "Clip_VRIWater",
    "Clip_WildfireTwentyYearsPlus", "Clip_RoadsPipelinesRailways",
    "Clip_PrivateLands",
]

# These layers are lower priority than the VRI/Results/FTA base openings.
# They are processed in this order and only their non-overlapping portions are
# appended. Keep the names synchronized with spreadsheet Short_Name values
# (prefixed with "Clip_").
LOWER_PRIORITY_OPENINGS = (
    "Clip_ConsolidatedCB",
    "Clip_WildfireCurrent",
    "Clip_WildfireTwentyYears",
)

# Layers that get an ECAsrc field (vs ECAsrc_1)
LAYERS_WITH_ECA_SRC = {"Clip_VRIOpeningsandBurns"}

# ---------------------------------------------------------------------------
# Aspect remap ranges (value * 10 to preserve precision before integer truncation)
# Format: [min, max, output_class]
# Classes: 0=Flat, 1=N, 2=NE, 3=E, 4=SE, 5=S, 6=SW, 7=W, 8=NW
# ---------------------------------------------------------------------------
ASPECT_REMAP = [
    [-10, -1, 0],
    [0, 225, 1], [225, 675, 2], [675, 1125, 3], [1125, 1575, 4],
    [1575, 2025, 5], [2025, 2475, 6], [2475, 2925, 7], [2925, 3375, 8],
    [3375, 3600, 1],
]

# Slope remap ranges (percent rise)
SLOPE_REMAP = [
    [0, 20, 20], [21, 40, 40], [41, 60, 60],
    [61, 80, 80], [81, 100, 100], [101, 1000, 1000],
]

# ---------------------------------------------------------------------------
# Recovery curves  (Kim Green, BCTS Kootenay hydrologist)
#
# The preferred approach is to load curves from the external Excel workbook
# (ECA_Recovery_Curves.xlsx) via load_recovery_curves().  The hardcoded
# dict below serves as a fallback when no workbook is provided.
#
# Structure: RECOVERY_CURVES[field_team][bec_zone] = (h0..h5, cc0..cc4)
#   h0-h5: height thresholds in metres
#   cc0-cc4: crown closure thresholds in percent
#
# Tuple layout: (h0, h1, h2, h3, h4, h5, cc0, cc1, cc2, cc3, cc4)
#   - h0..h5  are projected-height breakpoints
#   - cc0..cc4 are crown-closure breakpoints
#
# Special sentinel tuples:
#   all-zeros  -> BEC zone not applicable for this field team (error 998)
#   all-ones   -> field team not recognized (error 997)
#   all-twos   -> BEC subzone not recognized within zone (error 996)
# ---------------------------------------------------------------------------
_ZEROS = (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
_ONES = (1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1)
_TWOS = (2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2)
RECOVERY_PARAMETER_COLUMNS = ("h0", "h1", "h2", "h3", "h4", "h5", "cc0", "cc1", "cc2", "cc3", "cc4")

RECOVERY_CURVES = {
    "Boundary": {
        "ICH":  (5, 9, 11, 15, 20, 25, 15, 20, 30, 45, 55),
        "MS":   (5, 8, 10, 14, 18, 22, 15, 20, 30, 40, 50),
        "ESSF": {
            "dcp": (5, 7, 9, 13, 16, 20, 15, 20, 30, 40, 50),
            "mh":  (5, 8, 10, 14, 18, 23, 15, 20, 30, 40, 50),
            "dc":  (5, 7, 9, 12, 15, 19, 15, 20, 30, 40, 50),
            "dcw": (5, 7, 9, 11, 14, 17, 15, 20, 30, 35, 40),
            "_default": _TWOS,
        },
        "IDF":  (5, 9, 11, 15, 19, 24, 15, 20, 30, 40, 50),
        "PP":   (5, 9, 11, 15, 20, 24, 15, 20, 30, 40, 50),
        "_default": _ZEROS,
    },
    "Arrow": {
        "ICH":  (5, 9, 11, 16, 21, 26, 15, 20, 30, 40, 50),
        "ESSF": (4, 7, 9, 13, 16, 20, 15, 20, 30, 35, 45),
        "_default": _ZEROS,
    },
    "Kootenay Lake": {
        "ICH":  (5, 9, 11, 16, 21, 26, 15, 20, 30, 40, 50),
        "ESSF": (4, 7, 9, 13, 16, 20, 15, 20, 30, 35, 40),
        "_default": _ZEROS,
    },
    "Invermere": {
        "ICH":  (5, 9, 11, 15, 20, 25, 15, 20, 30, 40, 50),
        "MS":   (5, 9, 11, 15, 20, 25, 15, 20, 30, 40, 50),
        "IDF":  (5, 9, 11, 15, 19, 24, 15, 20, 30, 35, 40),
        "ESSF": (5, 7, 9, 13, 16, 20, 15, 20, 30, 40, 50),
        "_default": _ZEROS,
    },
    "Cranbrook": {
        "ICH":  (5, 9, 11, 15, 20, 25, 15, 20, 30, 45, 55),
        "MS":   (5, 8, 10, 14, 18, 23, 15, 20, 30, 40, 50),
        "ESSF": (5, 7, 9, 11, 14, 17, 15, 20, 30, 35, 45),
        "IDF":  (5, 8, 10, 14, 18, 23, 15, 20, 30, 40, 50),
        "_default": _ZEROS,
    },
    "_default": _ONES,
}


def get_recovery_params(field_team, bec_zone, bec_subzone=None, curves=None):
    """Look up recovery curve parameters for a field team / BEC zone combo.

    If *curves* is provided, uses that dict instead of the module-level
    ``RECOVERY_CURVES``.  This allows curves loaded from an external Excel
    workbook (via :func:`load_recovery_curves`) to be used.

    Returns a tuple of 11 values (h0..h5, cc0..cc4) or a sentinel tuple.
    """
    if curves is None:
        curves = RECOVERY_CURVES

    def lookup(mapping, key, default):
        if key in mapping:
            return mapping[key]
        normalized = " ".join(str(key).split()).casefold() if key is not None else ""
        return next(
            (value for candidate, value in mapping.items()
             if " ".join(str(candidate).split()).casefold() == normalized),
            default,
        )

    ft_curves = lookup(curves, field_team, curves.get("_default", _ONES))

    if isinstance(ft_curves, tuple):
        return ft_curves

    zone_val = lookup(ft_curves, bec_zone, ft_curves.get("_default", _ZEROS))

    if isinstance(zone_val, dict):
        return lookup(zone_val, bec_subzone, zone_val.get("_default", _TWOS))

    return zone_val


def load_recovery_curves(xlsx_path):
    """Load recovery curves from an Excel workbook.

    Each sheet represents a field team (tab name must match the
    ``Field_Team`` value in the feature class).  Returns a nested dict
    with the same structure as :data:`RECOVERY_CURVES`.
    """
    import pandas as pd

    xls = pd.ExcelFile(xlsx_path, engine="openpyxl")
    curves = {}

    for sheet_name in xls.sheet_names:
        team_name = sheet_name.strip()
        if team_name in curves:
            raise ValueError(f"Duplicate recovery sheet name after trimming: {team_name!r}")
        df = pd.read_excel(xls, sheet_name=sheet_name, engine="openpyxl")
        df.columns = df.columns.str.strip()
        df = df.where(pd.notnull(df), None)
        missing = sorted(set(("BEC_Zone", "BEC_Subzone", *RECOVERY_PARAMETER_COLUMNS)) - set(df.columns))
        if missing:
            raise ValueError(f"Recovery sheet {sheet_name!r} is missing columns: {', '.join(missing)}")

        def parameters(row, location):
            values = []
            for column in RECOVERY_PARAMETER_COLUMNS:
                try:
                    number = float(row[column])
                except (TypeError, ValueError) as error:
                    raise ValueError(f"{location} {column} must be numeric.") from error
                if not math.isfinite(number):
                    raise ValueError(f"{location} {column} must be finite.")
                values.append(int(number) if number.is_integer() else number)
            result = tuple(values)
            if result not in {_ZEROS, _ONES, _TWOS}:
                if any(left > right for left, right in zip(result[:6], result[1:6])):
                    raise ValueError(f"{location} height thresholds must be non-decreasing.")
                if any(left > right for left, right in zip(result[6:], result[7:])):
                    raise ValueError(f"{location} crown-closure thresholds must be non-decreasing.")
                if result[0] < 0 or result[6] < 0 or result[-1] > 100:
                    raise ValueError(f"{location} thresholds are outside their valid range.")
            return result

        team_curves = {}

        for zone, group in df.groupby("BEC_Zone", sort=False):
            zone_name = str(zone).strip()
            subzone_rows = group[group["BEC_Subzone"].notna()]
            zone_only_rows = group[group["BEC_Subzone"].isna()]

            if len(subzone_rows) > 0:
                # Zone has subzone-level entries -> build a sub-dict
                names = [str(value).strip() for value in subzone_rows["BEC_Subzone"]]
                if len(zone_only_rows) or len(names) != len(set(names)):
                    raise ValueError(
                        f"{team_name}/{zone_name} must use either one zone curve or unique subzone curves."
                    )
                zone_dict = {}
                for _, row in subzone_rows.iterrows():
                    sz = str(row["BEC_Subzone"]).strip()
                    zone_dict[sz] = parameters(row, f"{team_name}/{zone_name}/{sz}")
                zone_dict["_default"] = _TWOS
                team_curves[zone_name] = zone_dict
            elif len(zone_only_rows) == 1:
                # Single zone-level row -> store as tuple
                row = zone_only_rows.iloc[0]
                team_curves[zone_name] = parameters(row, f"{team_name}/{zone_name}")
            else:
                raise ValueError(f"{team_name}/{zone_name} contains more than one zone-level curve.")

        team_curves["_default"] = _ZEROS
        curves[team_name] = team_curves

    curves["_default"] = _ONES
    return curves
