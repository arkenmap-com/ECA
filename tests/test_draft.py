import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from open_eca.draft import AdditionalInput, run_draft


CURVES = {
    "Boundary": {"ICH": (5, 9, 11, 15, 20, 25, 15, 20, 30, 45, 55), "_default": (0,) * 11},
    "_default": (1,) * 11,
}


class DraftTests(unittest.TestCase):
    def test_runs_complete_draft_from_local_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            watershed_path = root / "watershed.geojson"
            gpd.GeoDataFrame(
                {"BASIN": ["Example Creek"], "SUB": ["Upper"]}, geometry=[box(0, 0, 20, 20)], crs="EPSG:3005",
            ).to_file(watershed_path, driver="GeoJSON")
            inputs_path = root / "inputs.gpkg"
            gpd.GeoDataFrame(
                {"OPENING_ID": [1], "CROWN_CLOSURE": [25], "PROJ_HEIGHT_1": [10]},
                geometry=[box(10, 0, 20, 20)], crs="EPSG:3005",
            ).to_file(inputs_path, layer="vri_openings", driver="GPKG")
            gpd.GeoDataFrame(
                {"ZONE": ["ICH"], "SUBZONE": ["xx"]}, geometry=[box(0, 0, 20, 20)], crs="EPSG:3005",
            ).to_file(inputs_path, layer="bec_zones", driver="GPKG", mode="a")
            dem_path = root / "dem.tif"
            with rasterio.open(
                dem_path, "w", driver="GTiff", height=2, width=2, count=1, dtype="float32",
                crs="EPSG:3005", transform=from_origin(0, 20, 10, 10), nodata=-9999,
            ) as destination:
                destination.write(np.array([[100, 200], [300, 400]], dtype="float32"), 1)

            additional_path = root / "local_harvest.geojson"
            gpd.GeoDataFrame(
                {"name": ["Local block"]}, geometry=[box(0, 0, 10, 20)], crs="EPSG:3005",
            ).to_file(additional_path, driver="GeoJSON")
            result = run_draft(
                watershed_path, "BASIN", "SUB", inputs_path, dem_path, CURVES, root / "draft", "Boundary",
                (AdditionalInput(additional_path, "Local harvest"),),
            )

            recovery = gpd.read_file(result.geopackage, layer="openings_recovery")
            self.assertEqual(result.basin, "Example Creek")
            self.assertEqual(result.field_team, "Boundary")
            self.assertAlmostEqual(result.h60_elevation, 220)
            self.assertEqual(set(recovery["Recovery"]), {0, 30})
            self.assertIn("Local harvest", set(recovery["ECAsrc"]))
            self.assertTrue((result.report_dir / "eca_summary.csv").exists())

            no_dem = run_draft(
                watershed_path, "BASIN", "SUB", inputs_path, None, CURVES, root / "draft_no_dem", "Boundary",
            )
            zones = gpd.read_file(no_dem.geopackage, layer="h60_zones")
            self.assertIsNone(no_dem.h60_elevation)
            self.assertEqual(zones["ELEVATION"].tolist(), ["Entire Watershed"])
            self.assertFalse((root / "draft_no_dem" / "clipped_dem.tif").exists())
