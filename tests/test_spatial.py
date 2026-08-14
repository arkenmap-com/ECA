import unittest

import geopandas as gpd
from shapely.geometry import LineString, Polygon

from open_eca.spatial import buffer_transport, clip_to_boundary


class SpatialTests(unittest.TestCase):
    def setUp(self):
        self.boundary = gpd.GeoDataFrame(
            {"name": ["basin"]}, geometry=[Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])], crs="EPSG:3005",
        )

    def test_clip_retains_source_attributes(self):
        features = gpd.GeoDataFrame(
            {"source": ["test"]}, geometry=[Polygon([(50, 50), (150, 50), (150, 150), (50, 150)])], crs="EPSG:3005",
        )
        clipped = clip_to_boundary(features, self.boundary)
        self.assertEqual(list(clipped.columns), ["source", "geometry"])
        self.assertEqual(clipped.loc[0, "source"], "test")
        self.assertAlmostEqual(clipped.geometry.area.iloc[0], 2500)

    def test_buffer_transport_dissolves_and_clips(self):
        road = gpd.GeoDataFrame(
            geometry=[LineString([(-20, 50), (120, 50)])], crs="EPSG:3005",
        )
        buffered = buffer_transport([(road, 4)], self.boundary)
        self.assertEqual(len(buffered), 1)
        self.assertAlmostEqual(buffered.geometry.area.iloc[0], 800)

    def test_buffer_rejects_non_positive_distance(self):
        road = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:3005")
        with self.assertRaisesRegex(ValueError, "positive"):
            buffer_transport([(road, 0)], self.boundary)
