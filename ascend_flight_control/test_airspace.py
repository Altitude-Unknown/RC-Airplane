#!/usr/bin/env python3
"""Offline tests for airspace_layers.py (no FAA requests)."""

from __future__ import annotations

import io
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
        self.assertEqual(set(A.BASE_MAPS), {"street", "sectional", "satellite"})
        for key in ("sectional", "satellite"):
            _label, url, max_zoom, credit = A.BASE_MAPS[key]
            self.assertIn(url, A.OVERZOOM, "deep zooms are enlarged, not fetched")
            self.assertGreater(max_zoom, A.OVERZOOM[url])
            self.assertTrue(credit)


class OverzoomTests(unittest.TestCase):
    """Tiles past a server's deepest zoom are cut from the deepest real tile (no network)."""

    def setUp(self):
        from PIL import Image
        self.requested = []
        # A 256 px parent tile: left half red, right half blue.
        parent = Image.new("RGB", (256, 256), (255, 0, 0))
        parent.paste((0, 0, 255), (128, 0, 256, 256))
        buf = io.BytesIO()
        parent.save(buf, "PNG")
        test = self

        class Response:
            content = buf.getvalue()
            status_code = 200

            def raise_for_status(self):
                pass

        def fake_get(url, **_kw):
            test.requested.append(url)
            return Response()

        self._real_get = A.requests.get
        A.requests.get = fake_get
        A._parent_tiles.clear()

    def tearDown(self):
        A.requests.get = self._real_get
        A._parent_tiles.clear()

    def test_native_zoom_fetches_that_tile(self):
        A.overzoom_tile(A.SATELLITE_TILES, 16, 12345, 23456)
        self.assertEqual(self.requested, [A.SATELLITE_TILES.replace("{z}", "16").replace("{y}", "23456")
                                          .replace("{x}", "12345")])

    def test_deeper_zoom_is_cut_from_the_native_tile(self):
        from PIL import Image
        # Zoom 17 tile (2x, y) is the left half of zoom-16 tile (x, y >> 1); (2x+1) is the right half.
        left = Image.open(A.overzoom_tile(A.SATELLITE_TILES, 17, 2 * 100, 2 * 50))
        right = Image.open(A.overzoom_tile(A.SATELLITE_TILES, 17, 2 * 100 + 1, 2 * 50))
        self.assertEqual(left.size, (256, 256))
        self.assertEqual(left.convert("RGB").getpixel((128, 128)), (255, 0, 0))
        self.assertEqual(right.convert("RGB").getpixel((128, 128)), (0, 0, 255))
        self.assertEqual(len(self.requested), 1, "the parent tile is fetched once and reused")
        self.assertIn("/tile/16/50/100", self.requested[0])

    def test_sectional_and_satellite_parents_are_cached_separately(self):
        A.overzoom_tile(A.SATELLITE_TILES, 17, 0, 0)
        A.sectional_tile(13, 0, 0)
        self.assertEqual(len(self.requested), 2)
        self.assertIn("/tile/12/0/0", self.requested[1])


if __name__ == "__main__":
    unittest.main()
