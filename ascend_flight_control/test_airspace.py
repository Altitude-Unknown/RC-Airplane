#!/usr/bin/env python3
"""Offline tests for airspace_layers.py (no FAA requests)."""

from __future__ import annotations

import unittest

import requests

import airspace_layers as A

SQUARE = [(45.0, -111.0), (45.0, -110.0), (46.0, -110.0), (46.0, -111.0), (45.0, -111.0)]


class GeometryTests(unittest.TestCase):
    def test_point_in_ring(self):
        self.assertTrue(A.point_in_ring(45.5, -110.5, SQUARE))
        self.assertFalse(A.point_in_ring(44.9, -110.5, SQUARE))
        self.assertFalse(A.point_in_ring(45.5, -109.9, SQUARE))

    def test_geojson_polygon_and_multipolygon(self):
        poly = {"type": "Polygon", "coordinates": [[[-111, 45], [-110, 45], [-110, 46], [-111, 45]],
                                                   [[-110.6, 45.4], [-110.4, 45.4], [-110.5, 45.6], [-110.6, 45.4]]]}
        rings = A.geojson_rings(poly)
        self.assertEqual(len(rings), 1, "holes are not drawn")
        self.assertEqual(rings[0][0], (45, -111), "GeoJSON is lon,lat; rings are lat,lon")
        multi = {"type": "MultiPolygon", "coordinates": [poly["coordinates"], [[[0, 0], [1, 0], [1, 1], [0, 0]]]]}
        self.assertEqual(len(A.geojson_rings(multi)), 2)
        self.assertEqual(A.geojson_rings(None), [])
        self.assertEqual(A.geojson_rings({"type": "Point", "coordinates": [1, 2]}), [])

    def test_feature_contains(self):
        f = A.Feature("tfr", [SQUARE], "t", "d", "#f00")
        self.assertTrue(f.contains(45.2, -110.2))
        self.assertFalse(f.contains(47, -110.2))

    def test_bbox_helpers(self):
        view = (45.0, -111.0, 46.0, -110.0)
        big = A.expand_bbox(view)
        self.assertTrue(A.bbox_contains(big, view))
        self.assertFalse(A.bbox_contains(view, big))
        self.assertEqual(A.expand_bbox((89.9, 179.9, 90.0, 180.0))[2:], (90.0, 180.0))


class TextTests(unittest.TestCase):
    def test_tfr_link(self):
        self.assertEqual(A.tfr_link("6/5945-1-FDC-F"), "https://tfr.faa.gov/tfr3/?page=detail_6_5945")
        self.assertEqual(A.tfr_link(""), "https://tfr.faa.gov/")

    def test_errors_are_plain_english(self):
        self.assertIn("busy", A.short_error(RuntimeError("Unable to perform query. Too many requests.")))
        self.assertIn("internet", A.short_error(requests.ConnectionError()))
        self.assertIn("did not answer", A.short_error(requests.Timeout()))

    def test_every_layer_is_described(self):
        for lid, layer in A.LAYERS.items():
            self.assertEqual(layer.id, lid)
            self.assertTrue(layer.name and layer.legend and layer.color.startswith("#"))
        self.assertIn("not for navigation", A.DISCLAIMER)
        self.assertEqual(set(A.BASE_MAPS), {"street", "sectional"})


if __name__ == "__main__":
    unittest.main()
