import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from open_eca.dem import derive_h60


class DemTests(unittest.TestCase):
    def test_derives_h60_zones_from_clipped_dem(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            dem_path = directory / "source.tif"
            with rasterio.open(
                dem_path, "w", driver="GTiff", height=2, width=2, count=1,
                dtype="float32", crs="EPSG:3005", transform=from_origin(0, 20, 10, 10), nodata=-9999,
            ) as destination:
                destination.write(np.array([[100, 200], [300, 400]], dtype="float32"), 1)
            watershed = gpd.GeoDataFrame(geometry=[box(0, 0, 20, 20)], crs="EPSG:3005")
            result = derive_h60(dem_path, watershed, directory / "clipped.tif", directory / "h60.gpkg")

            zones = gpd.read_file(result.zones, layer="h60_zones")
            self.assertAlmostEqual(result.percentile_40th, 220)
            self.assertEqual(set(zones["ELEVATION"]), {"H60 Above", "H60 Below"})
            self.assertAlmostEqual(zones["H60Area"].sum(), 0.04)
