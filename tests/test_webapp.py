import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
import numpy as np
import rasterio
from rasterio.transform import from_origin

from open_eca.recovery import calculate_recovery, get_params, load_curves
from webapp.app import CALIBRATED_CURVES, TEST_CURVES, create_app


class WebAppTests(unittest.TestCase):
    def test_health_and_home(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(Path(directory)))
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            home = client.get("/").text
            self.assertIn("Live BC data", home)
            self.assertIn("Calibrated Kootenay curves", home)
            self.assertIn("Synthetic test preset", home)
            self.assertIn("Testing only", home)
            self.assertIn('name="dem"', home)
            self.assertIn("Automatic NRCan 30 m", home)
            self.assertIn("H60 Above/Below", home)

    def test_dem_upload_is_passed_to_draft_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            source_dem = Path(directory) / "source.tif"
            with rasterio.open(
                source_dem, "w", driver="GTiff", height=1, width=1, count=1, dtype="float32",
                crs="EPSG:3005", transform=from_origin(0, 10, 10, 10), nodata=-9999,
            ) as destination:
                destination.write(np.array([[100]], dtype="float32"), 1)
            dem_payload = source_dem.read_bytes()
            result = SimpleNamespace(
                basin="Example Creek", h60_elevation=1234.5,
                geopackage=Path(directory) / "output" / "ECA_Draft.gpkg",
            )
            with (
                patch("webapp.app.download_named_watershed"),
                patch("webapp.app.run_draft", return_value=result) as run_draft,
                patch("webapp.app.create_dashboard"),
            ):
                response = TestClient(create_app(Path(directory))).post(
                    "/runs",
                    data={
                        "fwa_id": "1", "data_source": "upload", "curve_source": "calibrated",
                        "field_team": "Boundary", "dem_source": "upload",
                    },
                    files={
                        "inputs": ("inputs.gpkg", b"prepared cache", "application/geopackage+sqlite3"),
                        "dem": ("elevation.tif", dem_payload, "image/tiff"),
                    },
                )
            self.assertEqual(response.status_code, 200)
            dem_path = run_draft.call_args.args[4]
            self.assertEqual(dem_path.suffix, ".tif")
            self.assertEqual(dem_path.read_bytes(), dem_payload)
            self.assertIn("H60 elevation: 1,234.5 m", response.text)
            self.assertIn("Download clipped DEM", response.text)

    def test_dem_upload_requires_geotiff_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            response = TestClient(create_app(Path(directory))).post(
                "/runs",
                data={
                    "fwa_id": "1", "data_source": "bc_live", "curve_source": "calibrated",
                    "field_team": "Boundary", "dem_source": "upload",
                },
                files={"dem": ("elevation.zip", b"not a raster", "application/zip")},
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn("georeferenced GeoTIFF", response.json()["detail"])

    def test_dem_upload_rejects_unreadable_tiff(self):
        with tempfile.TemporaryDirectory() as directory:
            response = TestClient(create_app(Path(directory))).post(
                "/runs",
                data={
                    "fwa_id": "1", "data_source": "bc_live", "curve_source": "calibrated",
                    "field_team": "Boundary", "dem_source": "upload",
                },
                files={"dem": ("elevation.tif", b"not a raster", "image/tiff")},
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "The DEM is not a readable GeoTIFF.")

    def test_automatic_dem_is_acquired_and_passed_to_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            automatic_dem = root / "automatic.tif"
            automatic_dem.write_bytes(b"automatic DEM")
            acquired = SimpleNamespace(
                path=automatic_dem,
                source=SimpleNamespace(title="NRCan MRDEM 30 m terrain model"),
            )
            result = SimpleNamespace(
                basin="Example Creek", h60_elevation=987.6,
                geopackage=root / "output" / "ECA_Draft.gpkg",
            )
            with (
                patch("webapp.app.download_named_watershed"),
                patch("webapp.app.acquire_nrcan_dem", return_value=acquired) as acquire_dem,
                patch("webapp.app.run_draft", return_value=result) as run_draft,
                patch("webapp.app.create_dashboard"),
            ):
                response = TestClient(create_app(root)).post(
                    "/runs",
                    data={
                        "fwa_id": "1", "data_source": "upload", "curve_source": "calibrated",
                        "field_team": "Boundary", "dem_source": "auto",
                    },
                    files={"inputs": ("inputs.gpkg", b"cache", "application/geopackage+sqlite3")},
                )
            self.assertEqual(response.status_code, 200)
            acquire_dem.assert_called_once()
            self.assertEqual(run_draft.call_args.args[4], automatic_dem)
            self.assertIn("NRCan MRDEM 30 m terrain model", response.text)

    def test_calibrated_curves_are_the_operational_default(self):
        curves = load_curves(CALIBRATED_CURVES)
        boundary_ich = get_params("Boundary", "ICH", None, curves)
        self.assertEqual(boundary_ich, (5, 9, 11, 15, 20, 25, 15, 20, 30, 45, 55))
        with tempfile.TemporaryDirectory() as directory:
            response = TestClient(create_app(Path(directory))).get("/calibrated-recovery-curves.xlsx")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"PK"))

    def test_synthetic_curves_are_available_and_plausible(self):
        curves = load_curves(TEST_CURVES)
        fast = get_params("Synthetic Test", "CWH", None, curves)
        slow = get_params("Synthetic Test", "PP", None, curves)
        self.assertEqual(calculate_recovery(10, 35, fast), 70)
        self.assertEqual(calculate_recovery(10, 35, slow), 30)
        with tempfile.TemporaryDirectory() as directory:
            response = TestClient(create_app(Path(directory))).get("/test-recovery-curves.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Synthetic Test", response.json())

    def test_uploaded_curve_mode_requires_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            response = TestClient(create_app(Path(directory))).post(
                "/runs",
                data={
                    "fwa_id": "1",
                    "data_source": "bc_live",
                    "curve_source": "upload",
                    "field_team": "Boundary",
                },
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Upload a recovery-curve workbook or JSON file.")

    def test_calibrated_mode_rejects_unknown_field_team(self):
        with tempfile.TemporaryDirectory() as directory:
            response = TestClient(create_app(Path(directory))).post(
                "/runs",
                data={
                    "fwa_id": "1",
                    "data_source": "bc_live",
                    "curve_source": "calibrated",
                    "field_team": "Synthetic Test",
                },
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn("calibrated Kootenay workbook", response.json()["detail"])

    def test_environment_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hosted-runs"
            with patch.dict(os.environ, {"ECA_DATA_DIR": str(target)}):
                create_app()
            self.assertTrue(target.is_dir())


if __name__ == "__main__":
    unittest.main()
