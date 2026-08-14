import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

from open_eca.watershed import prepare_watershed


class WatershedTests(unittest.TestCase):
    def _source(self) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(
            {"BASIN": ["Example Creek", "Example Creek"], "SUB": ["Upper", None]},
            geometry=[
                Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]),
                Polygon([(100, 0), (200, 0), (200, 100), (100, 100)]),
            ],
            crs="EPSG:3005",
        )

    def test_writes_canonical_watershed_layers(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "subbasins.geojson"
            output_path = Path(directory) / "watershed.gpkg"
            self._source().to_file(source_path, driver="GeoJSON")

            result = prepare_watershed(source_path, "BASIN", "SUB", output_path)

            watershed = gpd.read_file(output_path, layer="watershed")
            subbasins = gpd.read_file(output_path, layer="subbasins")
            self.assertEqual(result.basin, "Example Creek")
            self.assertAlmostEqual(result.basin_area_ha, 2.0)
            self.assertEqual(watershed.loc[0, "Watershed"], "Example Creek")
            self.assertEqual(len(subbasins), 2)
            self.assertEqual(subbasins.loc[1, "Sub_Basin"], "Example Creek")
            self.assertTrue((subbasins["SubBasinArea"] == 1.0).all())

    def test_rejects_multiple_basin_names(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "subbasins.geojson"
            output_path = Path(directory) / "watershed.gpkg"
            frame = self._source()
            frame.loc[1, "BASIN"] = "Other Creek"
            frame.to_file(source_path, driver="GeoJSON")
            with self.assertRaisesRegex(ValueError, "exactly one"):
                prepare_watershed(source_path, "BASIN", "SUB", output_path)
