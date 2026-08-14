import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from webapp.app import create_app


class WebAppTests(unittest.TestCase):
    def test_health_and_home(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(Path(directory)))
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            self.assertIn("Live BC data", client.get("/").text)

    def test_environment_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hosted-runs"
            with patch.dict(os.environ, {"ECA_DATA_DIR": str(target)}):
                create_app()
            self.assertTrue(target.is_dir())


if __name__ == "__main__":
    unittest.main()
