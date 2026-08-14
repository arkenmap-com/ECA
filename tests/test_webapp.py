import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from open_eca.recovery import calculate_recovery, get_params, load_curves
from webapp.app import TEST_CURVES, create_app


class WebAppTests(unittest.TestCase):
    def test_health_and_home(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(Path(directory)))
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            home = client.get("/").text
            self.assertIn("Live BC data", home)
            self.assertIn("Synthetic test preset", home)
            self.assertIn("Testing only", home)

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

    def test_environment_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hosted-runs"
            with patch.dict(os.environ, {"ECA_DATA_DIR": str(target)}):
                create_app()
            self.assertTrue(target.is_dir())


if __name__ == "__main__":
    unittest.main()
