import unittest

import geopandas as gpd
from shapely.geometry import box

from open_eca.openings import append_lower_priority, build_other_openings, merge_base_openings, split_openings


def frame(ids, geometries, crowns=None, heights=None):
    return gpd.GeoDataFrame(
        {
            "OPENING_ID": ids,
            "CROWN_CLOSURE": crowns or [30] * len(ids),
            "PROJ_HEIGHT_1": heights or [10] * len(ids),
        }, geometry=geometries, crs="EPSG:3005",
    )


class OpeningTests(unittest.TestCase):
    def test_base_merge_keeps_vri_for_matching_id_and_replaces_overlap_for_new_id(self):
        vri = frame([1], [box(0, 0, 10, 10)])
        results = frame([1, 2], [box(0, 0, 10, 10), box(5, 0, 15, 10)])
        merged = merge_base_openings(vri, results)
        self.assertEqual(set(merged["OPENING_ID"]), {1, 2})
        self.assertEqual(merged.loc[merged["OPENING_ID"] == 1, "ECAsrc"].iloc[0], "VRI Openings and Burns")
        added = merged.loc[merged["OPENING_ID"] == 2].iloc[0]
        self.assertEqual(added["CROWN_CLOSURE"], 0)
        self.assertAlmostEqual(merged.geometry.area.sum(), 150)

    def test_lower_priority_only_fills_uncovered_area(self):
        base = merge_base_openings(frame([1], [box(0, 0, 10, 10)]))
        merged = append_lower_priority(base, [(frame([2], [box(5, 0, 15, 10)]), "Wildfire")])
        self.assertEqual(len(merged), 2)
        self.assertAlmostEqual(merged.geometry.area.sum(), 150)
        self.assertAlmostEqual(merged.loc[merged["ECAsrc"] == "Wildfire", "Hectares"].iloc[0], 0.005)

    def test_empty_lower_priority_layer_preserves_recovery_fields(self):
        vri = gpd.GeoDataFrame(
            {"OPENING_ID": [], "CROWN_CLOSURE": [], "PROJ_HEIGHT_1": []},
            geometry=[], crs="EPSG:3005",
        )
        empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:3005")
        merged = append_lower_priority(merge_base_openings(vri), [(empty, "Empty")])
        self.assertTrue(merged.empty)
        self.assertTrue({"CROWN_CLOSURE", "PROJ_HEIGHT_1"}.issubset(merged.columns))

    def test_splits_openings_by_h60_and_subbasin(self):
        openings = merge_base_openings(frame([1], [box(0, 0, 20, 10)]))
        h60 = gpd.GeoDataFrame(
            {"ELEVATION": ["H60 Below", "H60 Above"]},
            geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10)], crs="EPSG:3005",
        )
        subbasins = gpd.GeoDataFrame({"Sub_Basin": ["Whole"]}, geometry=[box(0, 0, 20, 10)], crs="EPSG:3005")
        split = split_openings(openings, h60, subbasins)
        self.assertEqual(set(split["ELEVATION"]), {"H60 Above", "H60 Below"})
        self.assertTrue((split["Sub_Basin"] == "Whole").all())
        self.assertAlmostEqual(split["Hectares"].sum(), 0.02)

    def test_other_openings_do_not_overlap_main_or_each_other(self):
        main = merge_base_openings(frame([1], [box(0, 0, 10, 10)]))
        other = build_other_openings(
            main,
            [(frame([2], [box(5, 0, 15, 10)]), "Roads"), (frame([3], [box(10, 0, 20, 10)]), "Water")],
        )
        self.assertAlmostEqual(other.geometry.area.sum(), 100)
