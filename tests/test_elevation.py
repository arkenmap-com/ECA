import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from open_eca.elevation import DemSource, acquire_nrcan_dem, discover_nrcan_mrdem


class ElevationAcquisitionTests(unittest.TestCase):
    def _watershed(self, root: Path) -> Path:
        path = root / "watershed.geojson"
        gpd.GeoDataFrame(geometry=[box(0, 0, 40, 40)], crs="EPSG:3005").to_file(path, driver="GeoJSON")
        return path

    def test_discovers_terrain_asset_from_official_stac_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            watershed = self._watershed(Path(directory))
            response = io.BytesIO(json.dumps({"features": [{
                "collection": "mrdem-30", "id": "mrdem",
                "assets": {"dtm": {"href": "https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif"}},
            }]}).encode())
            with patch("open_eca.elevation.urlopen", return_value=response):
                source = discover_nrcan_mrdem(watershed)
            self.assertEqual(source.collection, "mrdem-30")
            self.assertEqual(source.asset, "dtm")

    def test_acquires_clipped_dem_and_writes_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            watershed = self._watershed(root)
            source_path = root / "national-dtm.tif"
            with rasterio.open(
                source_path, "w", driver="GTiff", height=4, width=4, count=1, dtype="float32",
                crs="EPSG:3005", transform=from_origin(0, 40, 10, 10), nodata=-9999,
            ) as destination:
                destination.write(np.arange(16, dtype="float32").reshape(4, 4), 1)
            source = DemSource("mrdem-30", "mrdem", "dtm", str(source_path), "NRCan test terrain model")
            output = root / "inputs" / "nrcan_mrdem.tif"
            with patch("open_eca.elevation.discover_nrcan_mrdem", return_value=source):
                result = acquire_nrcan_dem(watershed, output)

            self.assertTrue(result.path.is_file())
            self.assertTrue(result.provenance.is_file())
            provenance = json.loads(result.provenance.read_text(encoding="utf-8"))
            self.assertEqual(provenance["provider"], "Natural Resources Canada")
            self.assertEqual(provenance["source"]["asset"], "dtm")
            self.assertEqual(provenance["output_sha256"], result.sha256)


if __name__ == "__main__":
    unittest.main()
