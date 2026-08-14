import unittest
import json
import tempfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

from core.config import RECOVERY_CURVES
from open_eca.recovery import apply_recovery, calculate_recovery, get_params, load_curves


PARAMS = (5, 9, 11, 15, 20, 25, 15, 20, 30, 45, 55)
CURVES = {"Boundary": {"ICH": PARAMS, "_default": (0,) * 11}, "_default": (1,) * 11}


class RecoveryTests(unittest.TestCase):
    def test_calculates_recovery(self):
        self.assertEqual(calculate_recovery(10, 25, PARAMS), 30)
        self.assertEqual(calculate_recovery(26, 50, PARAMS), 100)

    def test_complete_matrix_and_exact_boundaries(self):
        # One representative point in every cell of the documented 7 x 6 matrix.
        heights = [4, 5, 9, 11, 15, 20, 25]
        crowns = [14, 15, 20, 30, 45, 55]
        expected = [
            [0, 0, 0, 0, 0, 0],
            [0, 10, 20, 30, 30, 30],
            [0, 20, 30, 50, 50, 50],
            [0, 30, 50, 70, 80, 80],
            [0, 30, 50, 70, 80, 90],
            [0, 30, 50, 70, 90, 100],
            [0, 30, 50, 70, 100, 100],
        ]
        self.assertEqual(
            [[calculate_recovery(height, crown, PARAMS) for crown in crowns] for height in heights],
            expected,
        )

    def test_decimal_thresholds_and_normalized_labels_are_preserved(self):
        payload = {
            "Boundary": {"ICH": [5.5, 9, 11, 15, 20, 25, 15, 20, 30, 45, 55], "_default": [0] * 11},
            "_default": [1] * 11,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "curves.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            curves = load_curves(path)
        params = get_params(" boundary ", "ich", None, curves)
        self.assertEqual(params[0], 5.5)
        self.assertEqual(calculate_recovery(5.25, 100, params), 0)
        self.assertEqual(calculate_recovery(5.5, 100, params), 30)

    def test_bundled_workbook_loads_without_optional_excel_dependency(self):
        path = Path(__file__).parents[1] / "templates" / "TKO_ECA_Recovery_Curves.xlsx"
        curves = load_curves(path)
        self.assertEqual(get_params("Boundary", "ICH", None, curves), PARAMS)
        self.assertEqual(curves, RECOVERY_CURVES)

    def test_rejects_invalid_curve_order(self):
        payload = {"Team": {"ICH": [5, 4, 11, 15, 20, 25, 15, 20, 30, 45, 55]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "curves.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-decreasing"):
                load_curves(path)

    def test_applies_override_and_reports_invalid_team(self):
        frame = gpd.GeoDataFrame(
            {
                "Field_Team": ["Boundary", "Unknown"], "ZONE": ["ICH", "ICH"],
                "SUBZONE": [None, None], "PROJ_HEIGHT_1": [10, 10], "CROWN_CLOSURE": [25, 25],
                "Override": [80, -1],
            }, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:3005",
        )
        result = apply_recovery(frame, CURVES, has_override=True)
        self.assertEqual(list(result["Recovery"]), [80, 0])
        self.assertEqual(list(result["Error"]), ["None", "Field Team Error"])

    def test_rejects_out_of_range_override(self):
        frame = gpd.GeoDataFrame(
            {
                "Field_Team": ["Boundary"], "ZONE": ["ICH"], "SUBZONE": [None],
                "PROJ_HEIGHT_1": [10], "CROWN_CLOSURE": [25], "Override": [120],
            }, geometry=[Point(0, 0)], crs="EPSG:3005",
        )
        with self.assertRaisesRegex(ValueError, "between 0 and 100"):
            apply_recovery(frame, CURVES, has_override=True)
