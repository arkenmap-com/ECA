import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from datetime import date

from open_eca.data_acquisition import LayerSource, _parse_bbox, _resolve_relative_dates, _split_large_in_filter, load_sources, watershed_bbox, wfs_command


class DataAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.source = LayerSource(
            name="vri_openings",
            service_url="https://example.test/wfs?",
            type_name="pub:VRI",
            catalogue_record="https://catalogue.example.test/vri",
            where="OPENING_IND = 'Y'",
        )

    def test_first_layer_creates_a_geopackage(self):
        command = wfs_command(self.source, "inputs.gpkg", (1, 2, 3, 4), append=False)
        self.assertNotIn("-append", command)
        self.assertIn("-spat", command)
        self.assertIn("OPENING_IND = 'Y'", command)

    def test_following_layer_appends(self):
        command = wfs_command(self.source, "inputs.gpkg", (1, 2, 3, 4), append=True)
        self.assertEqual(command[:3], ["ogr2ogr", "-update", "-append"])

    def test_relative_date_filter_is_resolved_for_ogr(self):
        self.assertEqual(
            _resolve_relative_dates("FIRE_DATE >= CURRENT_TIMESTAMP - 7305", date(2026, 8, 13)),
            "FIRE_DATE >= '2006-08-13'",
        )

    def test_all_relative_dates_in_compound_filter_are_resolved(self):
        expression = (
            "END_DATE >= CURRENT_TIMESTAMP - 7305 OR "
            "DENUDATION_DATE >= CURRENT_TIMESTAMP - 7305"
        )
        self.assertEqual(
            _resolve_relative_dates(expression, date(2026, 8, 13)),
            "END_DATE >= '2006-08-13' OR DENUDATION_DATE >= '2006-08-13'",
        )

    def test_long_simple_in_filter_is_split_into_disjoint_requests(self):
        filters = _split_large_in_filter("CODE IN ('A', 'B', 'C', 'D', 'E')", chunk_size=2)
        self.assertEqual(filters, ["CODE IN ('A', 'B')", "CODE IN ('C', 'D')", "CODE IN ('E')"])

    def test_compound_filter_is_not_split(self):
        expression = "A = 1 OR CODE IN ('A', 'B', 'C')"
        self.assertEqual(_split_large_in_filter(expression, chunk_size=2), [expression])

    def test_bbox_requires_four_numbers(self):
        self.assertEqual(_parse_bbox(["1", "2", "3", "4"]), (1.0, 2.0, 3.0, 4.0))
        with self.assertRaises(Exception):
            _parse_bbox(["1", "2", "3"])

    def test_starter_configuration_loads(self):
        sources = load_sources(Path("open_eca/config/bc_catalogue_layers.json"))
        self.assertIn("vri_openings", [source.name for source in sources])
        self.assertIn("results_openings", [source.name for source in sources])
        self.assertIn("bec_zones", [source.name for source in sources])
        self.assertTrue(next(source for source in sources if source.name == "vri_openings").catalogue_record)
        results = next(source for source in sources if source.name == "results_openings")
        self.assertEqual(results.type_name, "pub:WHSE_FOREST_VEGETATION.RSLT_OPENING_SVW")
        self.assertIn("OPENING_STATUS_CODE <> 'RET'", results.where)
        self.assertIn("CURRENT_TIMESTAMP - 7305", results.where)
        forest_cover = next(source for source in sources if source.name == "results_forest_cover")
        self.assertIn("56ac43a7-724a-4f01-b193-d5f9a16ef0a8", forest_cover.catalogue_record)

    def test_watershed_bbox_projects_to_bc_albers_and_adds_padding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watershed.geojson"
            gpd.GeoDataFrame(geometry=[box(1000, 2000, 3000, 4000)], crs="EPSG:3005").to_file(path)
            self.assertEqual(watershed_bbox(path, 100), (900.0, 1900.0, 3100.0, 4100.0))

    def test_watershed_bbox_rejects_negative_padding(self):
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            watershed_bbox(Path("unused.geojson"), -1)
