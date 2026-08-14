import unittest

import geopandas as gpd
from shapely.geometry import Point

from open_eca.recovery import apply_recovery, calculate_recovery


PARAMS = (5, 9, 11, 15, 20, 25, 15, 20, 30, 45, 55)
CURVES = {"Boundary": {"ICH": PARAMS, "_default": (0,) * 11}, "_default": (1,) * 11}


class RecoveryTests(unittest.TestCase):
    def test_calculates_recovery(self):
        self.assertEqual(calculate_recovery(10, 25, PARAMS), 30)
        self.assertEqual(calculate_recovery(26, 50, PARAMS), 100)

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
