#!/usr/bin/env python3
"""Tests for survey grid planning."""

from __future__ import annotations

import math
import unittest

import grid_survey as gs

LAT, LON = 45.64, -111.19


def box_m(width_e: float, height_n: float):
    """Box of the given size (meters) centered on LAT, LON."""
    frame = gs.LocalFrame(LAT, LON)
    a = frame.to_latlon(-width_e / 2, -height_n / 2)
    b = frame.to_latlon(width_e / 2, height_n / 2)
    return gs.box_corners(a, b), frame


class GridTests(unittest.TestCase):
    def test_fixed_spacing_north_south_passes(self):
        area, frame = box_m(200, 400)
        r = gs.plan_grid(area, gs.GridSettings(spacing_mode="fixed", spacing_m=50, angle_deg=0, runout_m=0))
        self.assertIsNone(r.error)
        self.assertEqual(r.passes, 4)
        self.assertEqual(len(r.points), 8)
        xy = [frame.to_xy(*p) for p in r.points]
        xs = sorted({round(x, 3) for x, _y in xy})
        self.assertEqual(xs, [-75.0, -25.0, 25.0, 75.0])  # centered across the 200 m width
        for x, y in xy:
            self.assertAlmostEqual(abs(y), 200.0, places=3)  # passes span the full 400 m
        # Serpentine: each pass starts where the previous one ended (same end of the box).
        self.assertAlmostEqual(xy[1][1], xy[2][1], places=3)
        self.assertAlmostEqual(r.area_m2, 80_000, delta=5)

    def test_runout_extends_each_pass(self):
        area, frame = box_m(100, 300)
        r = gs.plan_grid(area, gs.GridSettings(spacing_mode="fixed", spacing_m=50, angle_deg=0, runout_m=40))
        for x, y in (frame.to_xy(*p) for p in r.points):
            self.assertAlmostEqual(abs(y), 190.0, places=3)

    def test_camera_spacing_from_overlap(self):
        s = gs.GridSettings(altitude_m=100, camera_hfov_deg=90, camera_vfov_deg=90,
                            side_overlap_pct=50, front_overlap_pct=75)
        spacing, across, along, photo = gs.pass_spacing(s)
        self.assertAlmostEqual(across, 200.0, places=6)  # 2 * 100 * tan(45°)
        self.assertAlmostEqual(spacing, 100.0, places=6)
        self.assertAlmostEqual(photo, 50.0, places=6)

    def test_auto_angle_follows_longest_edge(self):
        area, frame = box_m(600, 100)  # long east-west
        r = gs.plan_grid(area, gs.GridSettings(spacing_mode="fixed", spacing_m=30, runout_m=0))
        self.assertAlmostEqual(r.angle_deg % 180, 90.0, places=3)
        xy = [frame.to_xy(*p) for p in r.points]
        self.assertAlmostEqual(xy[0][1], xy[1][1], places=3)  # first pass runs east-west

    def test_rotated_passes_stay_parallel_and_spaced(self):
        area, frame = box_m(300, 300)
        r = gs.plan_grid(area, gs.GridSettings(spacing_mode="fixed", spacing_m=40, angle_deg=30, runout_m=0))
        xy = [frame.to_xy(*p) for p in r.points]
        h = math.radians(30)
        for i in range(0, len(xy), 2):
            dx, dy = xy[i + 1][0] - xy[i][0], xy[i + 1][1] - xy[i][1]
            self.assertAlmostEqual(math.degrees(math.atan2(dx, dy)) % 180, 30.0, places=3)
        # Distance between neighboring passes, measured across the heading.
        across = [x * math.cos(h) - y * math.sin(h) for x, y in xy[::2]]
        for a, b in zip(across, across[1:]):
            self.assertAlmostEqual(abs(b - a), 40.0, places=3)

    def test_start_corner_choices(self):
        area, frame = box_m(200, 400)
        base = dict(spacing_mode="fixed", spacing_m=50, angle_deg=0, runout_m=0)
        starts = set()
        for corner in range(4):
            r = gs.plan_grid(area, gs.GridSettings(start_corner=corner, **base))
            x, y = frame.to_xy(*r.points[0])
            starts.add((round(x), round(y)))
        self.assertEqual(len(starts), 4)

    def test_triangle_passes_shrink(self):
        frame = gs.LocalFrame(LAT, LON)
        area = [frame.to_latlon(0, 0), frame.to_latlon(400, 0), frame.to_latlon(0, 400)]
        r = gs.plan_grid(area, gs.GridSettings(spacing_mode="fixed", spacing_m=50, angle_deg=90, runout_m=0))
        self.assertIsNone(r.error)
        lengths = [math.dist(frame.to_xy(*r.points[i]), frame.to_xy(*r.points[i + 1]))
                   for i in range(0, len(r.points), 2)]
        self.assertIn(lengths, (sorted(lengths), sorted(lengths, reverse=True)))
        self.assertLess(lengths[0], lengths[-1] / 3)

    def test_errors_and_limits(self):
        area, _ = box_m(200, 200)
        self.assertIsNotNone(gs.plan_grid(area[:2], gs.GridSettings()).error)
        self.assertIsNotNone(gs.plan_grid(area, gs.GridSettings(spacing_mode="fixed", spacing_m=0.1)).error)
        self.assertIn("limit", gs.plan_grid(box_m(20000, 200)[0],
                                            gs.GridSettings(spacing_mode="fixed", spacing_m=5, angle_deg=0)).error)
        self.assertIsNotNone(gs.plan_grid(area, gs.GridSettings(side_overlap_pct=99)).error)

    def test_bow_tie_is_refused(self):
        frame = gs.LocalFrame(LAT, LON)
        area = [frame.to_latlon(*p) for p in ((0, 0), (200, 200), (200, 0), (0, 200))]
        r = gs.plan_grid(area, gs.GridSettings(spacing_mode="fixed", spacing_m=50))
        self.assertIn("cross", r.error)


class PhotoEventTests(unittest.TestCase):
    def test_per_pass_on_and_off(self):
        self.assertEqual(gs.photo_events(6, 25.0, per_pass=True), [25.0, 0.0, 25.0, 0.0, 25.0, 0.0])

    def test_whole_grid(self):
        self.assertEqual(gs.photo_events(6, 25.0, per_pass=False), [25.0, None, None, None, None, 0.0])

    def test_nothing_without_distance(self):
        self.assertEqual(gs.photo_events(4, 0, per_pass=True), [None] * 4)


if __name__ == "__main__":
    unittest.main()
