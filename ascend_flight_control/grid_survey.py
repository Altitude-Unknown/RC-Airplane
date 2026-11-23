#!/usr/bin/env python3
"""
Survey grid ("lawnmower") planning for ASCEND Flight Control.

Give it an area (a box or any polygon of lat/lon corners) and the settings,
and it returns the waypoints for back-and-forth passes that cover the area:

- Pass spacing comes straight from the settings, or from the camera's field
  of view, the altitude and the side overlap between neighboring passes.
- Passes run at a chosen heading, or along the area's longest edge (fewest turns).
- Each pass runs past the area edge by a run-out distance so a fixed-wing
  plane has finished its turn and is flying straight before it is over the area.
- Each pass spans the area's full width at that line, so on a concave area
  (an L shape, say) some passes also fly over the notch.

Geometry is done on a flat local map (meters east/north of the area's center),
which is accurate for areas a few kilometers across.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

EARTH_M_PER_DEG = 111_320.0
MAX_PASSES = 300  # keeps a mistyped spacing from producing thousands of waypoints
START_CORNERS = ("first pass, first end", "first pass, far end", "last pass, first end", "last pass, far end")


@dataclass
class GridSettings:
    altitude_m: float = 100.0
    speed_mps: float = 15.0
    spacing_mode: str = "camera"  # "camera" (from field of view + overlap) or "fixed"
    spacing_m: float = 50.0  # used when spacing_mode == "fixed"
    camera_hfov_deg: float = 60.0  # field of view across the passes
    camera_vfov_deg: float = 45.0  # field of view along the passes (for photo spacing)
    side_overlap_pct: float = 60.0
    front_overlap_pct: float = 70.0
    angle_deg: float | None = None  # heading of the passes, degrees from north; None = along the longest edge
    runout_m: float = 40.0
    start_corner: int = 0  # index into START_CORNERS


@dataclass
class GridResult:
    points: list[tuple[float, float]] = field(default_factory=list)  # lat, lon in flying order
    passes: int = 0
    spacing_m: float = 0.0
    angle_deg: float = 0.0
    area_m2: float = 0.0
    distance_m: float = 0.0  # along the generated path, start to finish
    footprint_w_m: float | None = None  # camera footprint across the passes
    footprint_h_m: float | None = None  # camera footprint along the passes
    photo_spacing_m: float | None = None  # distance between photos for the front overlap
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


# -- flat local map ------------------------------------------------------------

class LocalFrame:
    """Meters east (x) / north (y) of a reference point."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0 = lat0
        self.lon0 = lon0
        self.kx = EARTH_M_PER_DEG * max(0.01, math.cos(math.radians(lat0)))

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * EARTH_M_PER_DEG

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        return self.lat0 + y / EARTH_M_PER_DEG, self.lon0 + x / self.kx


def frame_for(points: list[tuple[float, float]]) -> LocalFrame:
    return LocalFrame(sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def polygon_area_m2(xy: list[tuple[float, float]]) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def longest_edge_heading(xy: list[tuple[float, float]]) -> float:
    """Heading (0-180°, from north) of the polygon's longest edge."""
    best, heading = -1.0, 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        length = math.hypot(x2 - x1, y2 - y1)
        if length > best:
            best = length
            heading = math.degrees(math.atan2(x2 - x1, y2 - y1)) % 180.0
    return heading


def footprint_m(altitude_m: float, fov_deg: float) -> float:
    """Ground width a camera pointing straight down sees at this height."""
    return 2.0 * altitude_m * math.tan(math.radians(fov_deg) / 2.0)


def box_corners(a: tuple[float, float], b: tuple[float, float]) -> list[tuple[float, float]]:
    """North-aligned box from two opposite corners (lat, lon), corners in order around the box."""
    (lat1, lon1), (lat2, lon2) = a, b
    return [(lat1, lon1), (lat1, lon2), (lat2, lon2), (lat2, lon1)]


def self_intersects(points: list[tuple[float, float]]) -> bool:
    """True if two non-adjacent edges of the polygon cross (a "bow tie")."""
    n = len(points)
    if n < 4:
        return False

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    edges = [(points[i], points[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # neighbors share a corner
            p1, p2 = edges[i]
            p3, p4 = edges[j]
            d1, d2 = cross(p3, p4, p1), cross(p3, p4, p2)
            d3, d4 = cross(p1, p2, p3), cross(p1, p2, p4)
            if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
                return True
    return False


# -- grid --------------------------------------------------------------------

def pass_spacing(settings: GridSettings) -> tuple[float, float | None, float | None, float | None]:
    """(spacing, footprint across, footprint along, photo spacing) in meters."""
    across = footprint_m(settings.altitude_m, settings.camera_hfov_deg)
    along = footprint_m(settings.altitude_m, settings.camera_vfov_deg)
    photo = along * (1.0 - settings.front_overlap_pct / 100.0)
    if settings.spacing_mode == "camera":
        return across * (1.0 - settings.side_overlap_pct / 100.0), across, along, photo
    return settings.spacing_m, None, None, None


def plan_grid(area: list[tuple[float, float]], settings: GridSettings) -> GridResult:
    result = GridResult()
    if len(area) < 3:
        result.error = "Place at least three corners."
        return result
    if settings.altitude_m <= 0:
        result.error = "Altitude must be above zero."
        return result
    if settings.spacing_mode == "camera":
        if not 1 <= settings.camera_hfov_deg <= 170 or not 1 <= settings.camera_vfov_deg <= 170:
            result.error = "Camera field of view must be 1 to 170 degrees."
            return result
        if not 0 <= settings.side_overlap_pct <= 95 or not 0 <= settings.front_overlap_pct <= 95:
            result.error = "Overlap must be 0 to 95 %."
            return result
    if settings.runout_m < 0:
        result.error = "Run-out can't be negative."
        return result

    spacing, result.footprint_w_m, result.footprint_h_m, result.photo_spacing_m = pass_spacing(settings)
    if spacing <= 0.5:
        result.error = "Pass spacing must be more than 0.5 m."
        return result
    result.spacing_m = spacing

    frame = frame_for(area)
    xy = [frame.to_xy(lat, lon) for lat, lon in area]
    if self_intersects(xy):
        result.error = "The area's edges cross each other. Drag a corner to untangle it."
        return result
    result.area_m2 = polygon_area_m2(xy)
    if result.area_m2 < 1.0:
        result.error = "The area is too small. Spread the corners out."
        return result

    angle = longest_edge_heading(xy) if settings.angle_deg is None else settings.angle_deg % 360.0
    result.angle_deg = angle
    # Rotate so the passes run along +u: u = along the pass heading, v = across (to its right).
    a = math.radians(angle)
    ux, uy = math.sin(a), math.cos(a)  # heading unit vector (east, north)
    vx, vy = uy, -ux

    def to_uv(p):
        return p[0] * ux + p[1] * uy, p[0] * vx + p[1] * vy

    def from_uv(u, v):
        return u * ux + v * vx, u * uy + v * vy

    uv = [to_uv(p) for p in xy]
    vmin, vmax = min(p[1] for p in uv), max(p[1] for p in uv)
    width = vmax - vmin
    count = max(1, math.ceil(width / spacing - 1e-9))
    if count > MAX_PASSES:
        result.error = (f"That needs {count} passes (the limit is {MAX_PASSES}). "
                        "Use a smaller area, more spacing or less overlap.")
        return result
    # Center the passes across the area; with one pass it runs down the middle.
    first_v = vmin + (width - (count - 1) * spacing) / 2.0

    lines = []
    for i in range(count):
        v = first_v + i * spacing
        us = _crossings(uv, v)
        if len(us) < 2:
            continue
        lines.append((min(us) - settings.runout_m, max(us) + settings.runout_m, v))
    if not lines:
        result.error = "No passes fit in this area."
        return result

    corner = settings.start_corner % len(START_CORNERS)
    if corner >= 2:
        lines.reverse()
    flip_first = corner in (1, 3)
    points_uv = []
    for i, (u0, u1, v) in enumerate(lines):
        forward = (i % 2 == 0) != flip_first
        start, end = (u0, u1) if forward else (u1, u0)
        points_uv += [(start, v), (end, v)]

    pts_xy = [from_uv(u, v) for u, v in points_uv]
    result.points = [frame.to_latlon(x, y) for x, y in pts_xy]
    result.passes = len(lines)
    result.distance_m = sum(math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(pts_xy, pts_xy[1:]))

    if settings.spacing_mode == "camera" and settings.side_overlap_pct < 20:
        result.warnings.append("Side overlap under 20 % can leave gaps when the plane drifts in wind.")
    return result


def _crossings(uv: list[tuple[float, float]], v: float) -> list[float]:
    """u values where the line v = const crosses the polygon's edges."""
    us = []
    for (u1, v1), (u2, v2) in zip(uv, uv[1:] + uv[:1]):
        if v1 == v2:
            continue
        if min(v1, v2) <= v < max(v1, v2):  # passes always lie strictly inside the area's width
            t = (v - v1) / (v2 - v1)
            us.append(u1 + t * (u2 - u1))
    return us


def photo_events(point_count: int, photo_m: float, per_pass: bool) -> list[float | None]:
    """Photo-distance event for each grid waypoint (None = no event).

    Grid points come in pairs: the start and end of each pass. per_pass=True starts
    photos at each pass start and stops them at its end, so the camera is off in the
    turns; otherwise photos start at the first waypoint and stop at the last."""
    events: list[float | None] = [None] * point_count
    if point_count < 2 or photo_m <= 0:
        return events
    if per_pass:
        for i in range(0, point_count - 1, 2):
            events[i], events[i + 1] = photo_m, 0.0
    else:
        events[0], events[-1] = photo_m, 0.0
    return events
