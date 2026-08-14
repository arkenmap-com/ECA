import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from open_eca.dashboard import create_dashboard


class DashboardTests(unittest.TestCase):
    def test_writes_interactive_html_from_draft_layers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft = root / "ECA_Draft.gpkg"
            gpd.GeoDataFrame(
                {"Watershed": ["Example Creek"], "BasinArea": [1.0]}, geometry=[box(0, 0, 100, 100)], crs="EPSG:3005",
            ).to_file(draft, layer="watershed", driver="GPKG")
            gpd.GeoDataFrame(
                {"ECAsrc": ["VRI"], "ELEVATION": ["H60 Below"], "Hectares": [1.0], "ECA_Hectares": [0.7], "Recovery": [30]},
                geometry=[box(0, 0, 100, 100)], crs="EPSG:3005",
            ).to_file(draft, layer="openings_recovery", driver="GPKG", mode="a")
            output = create_dashboard(draft, root / "dashboard.html")
            text = output.read_text(encoding="utf-8")
            self.assertIn("Example Creek", text)
            self.assertIn("Recovering openings", text)
            self.assertIn("Filter mapped openings", text)
            self.assertIn("Total ECA", text)
            self.assertIn("Recovery %", text)
            self.assertIn("Opening type", text)
            self.assertIn("leaflet", text)
