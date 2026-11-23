#!/usr/bin/env python3
"""
FAA aeronautical map layers for ASCEND Flight Control (United States).

Base map:
- VFR sectional chart tiles from FAA Aeronautical Information Services
  (ArcGIS "VFR_Sectional", Web Mercator, zoom 0-12). Closer zooms reuse
  enlarged zoom-12 tiles.

Overlays (fetched for the area on screen, as GeoJSON):
- TFRs: live temporary flight restrictions from tfr.faa.gov.
- UAS Facility Map: the LAANC grid of maximum altitudes near airports.
- Controlled airspace where Part 107 needs authorization: Class B, C, D and
  the Class E surface areas (E2, plus E3/E4 extensions).
- Special use airspace: prohibited, restricted, warning, alert, MOA, danger.
- National security UAS flight restrictions (full and part-time) and
  national defense airspace areas.

For planning only. Pilots must still check NOTAMs and get LAANC or DroneZone
authorization; the app says so wherever it shows these layers.
"""

from __future__ import annotations

import io
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import requests
from PIL import Image

USER_AGENT = "ASCEND-Flight-Control/1.0"
HEADERS = {"User-Agent": USER_AGENT}
TIMEOUT_S = 30
ARCGIS = "https://services6.arcgis.com/ssFJjBXIUyZDrSYZ/arcgis/rest/services"

OSM_TILES = "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"
SECTIONAL_TILES = "https://tiles.arcgis.com/tiles/ssFJjBXIUyZDrSYZ/arcgis/rest/services/VFR_Sectional/MapServer/tile/{z}/{y}/{x}"
SECTIONAL_MAX_NATIVE_ZOOM = 12
SECTIONAL_MAX_ZOOM = 17
TFR_URL = ("https://tfr.faa.gov/geoserver/TFR/ows?service=WFS&version=1.1.0&request=GetFeature"
           "&typeName=TFR:V_TFR_LOC&maxFeatures=2000&outputFormat=application/json&srsname=EPSG:4326")
TFR_CACHE_S = 600

BASE_MAPS = {
    "street": ("Street map", OSM_TILES, 19, "© OpenStreetMap contributors"),
    "sectional": ("VFR sectional chart", SECTIONAL_TILES, SECTIONAL_MAX_ZOOM,
                  "Chart: FAA Aeronautical Information Services · not for navigation"),
}

DISCLAIMER = ("For planning only, not for navigation. These layers come from the FAA and can be out of date "
              "or incomplete. Before every flight, check NOTAMs and TFRs, and get LAANC or DroneZone "
              "authorization for controlled airspace (14 CFR 107.41 and 107.49). B4UFLY and your LAANC app "
              "have the final word.")


@dataclass
class Feature:
    layer: str
    rings: list[list[tuple[float, float]]]  # (lat, lon) outer rings
    title: str
    detail: str
    color: str
    fill: str | None = None
    dash: tuple | None = None
    label: str = ""  # short text drawn in the area (UAS Facility Map ceilings)
    link: str = ""

    def contains(self, lat: float, lon: float) -> bool:
        return any(point_in_ring(lat, lon, ring) for ring in self.rings)


@dataclass
class Layer:
    id: str
    name: str
    legend: str
    color: str
    min_zoom: int
    fetch: Callable[[tuple[float, float, float, float], int], list[Feature]] = field(repr=False)


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def point_in_ring(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def geojson_rings(geometry: dict | None) -> list[list[tuple[float, float]]]:
    """Outer rings of a Polygon / MultiPolygon as (lat, lon) lists. Holes are not drawn."""
    if not geometry:
        return []
    kind, coords = geometry.get("type"), geometry.get("coordinates") or []
    polygons = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else []
    rings = []
    for polygon in polygons:
        if polygon and len(polygon[0]) >= 3:
            rings.append([(pt[1], pt[0]) for pt in polygon[0]])
    return rings


def bbox_contains(outer, inner) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def expand_bbox(bbox, factor: float = 0.5):
    s, w, n, e = bbox
    dlat, dlon = (n - s) * factor, (e - w) * factor
    return max(-90.0, s - dlat), max(-180.0, w - dlon), min(90.0, n + dlat), min(180.0, e + dlon)


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------

def arcgis_query(service: str, bbox, where: str = "1=1", out_fields: str = "*", simplify: float = 0.0,
                 limit: int = 4000) -> list[dict]:
    """GeoJSON features of an FAA ArcGIS layer that touch bbox=(south, west, north, east)."""
    s, w, n, e = bbox
    features, offset = [], 0
    while True:
        params = {
            "where": where, "outFields": out_fields, "f": "geojson", "outSR": 4326, "inSR": 4326,
            "geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects", "returnGeometry": "true", "geometryPrecision": 6,
            "resultOffset": offset, "resultRecordCount": 2000,
        }
        if simplify > 0:
            params["maxAllowableOffset"] = simplify
        r = requests.get(f"{ARCGIS}/{service}/FeatureServer/0/query", params=params, headers=HEADERS,
                         timeout=TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", "FAA map service error"))
        batch = data.get("features", [])
        features += batch
        more = data.get("exceededTransferLimit") or data.get("properties", {}).get("exceededTransferLimit")
        if not more or not batch or len(features) >= limit:
            return features
        offset += len(batch)


def simplify_for(bbox) -> float:
    """Drop detail smaller than about a pixel (degrees), so big shapes stay quick to draw."""
    return max(0.00005, (bbox[3] - bbox[1]) / 1500.0)


def ft(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "?"
    return f"{v:,.0f} ft"


UASFM_COLORS = {0: "#b91c1c", 50: "#ea580c", 100: "#f59e0b", 200: "#eab308", 300: "#65a30d", 400: "#16a34a"}


def fetch_uasfm(bbox, zoom) -> list[Feature]:
    out = []
    for f in arcgis_query("FAA_UAS_FacilityMap_Data", bbox, out_fields="CEILING,UNIT,APT1_FAAID,APT1_NAME,APT1_LAANC"):
        p = f.get("properties") or {}
        ceiling = int(p.get("CEILING") or 0)
        airport = p.get("APT1_FAAID") or "a nearby airport"
        laanc = "LAANC can approve up to this altitude" if p.get("APT1_LAANC") else \
            "LAANC is not available here; request authorization through FAA DroneZone"
        detail = (f"Maximum altitude the FAA may authorize here without further review: {ceiling} ft above ground. "
                  f"Airport: {airport}. {laanc}.")
        if ceiling == 0:
            detail = (f"0 ft: no automatic authorization here (airport: {airport}). "
                      "Flights need an FAA DroneZone request with further coordination.")
        color = UASFM_COLORS.get(ceiling, "#16a34a" if ceiling > 400 else "#eab308")
        for ring in geojson_rings(f.get("geometry")):
            out.append(Feature("uasfm", [ring], f"UAS Facility Map: {ceiling} ft", detail, color, color,
                               label=str(ceiling)))
    return out


CLASS_STYLE = {
    "CLASS_B": ("#1d4ed8", None), "CLASS_C": ("#a21caf", None), "CLASS_D": ("#2563eb", (6, 4)),
    "CLASS_E2": ("#db2777", (6, 4)), "CLASS_E3": ("#db2777", (2, 4)), "CLASS_E4": ("#db2777", (2, 4)),
}


def fetch_class(bbox, zoom) -> list[Feature]:
    out = []
    where = "LOCAL_TYPE IN ('CLASS_B','CLASS_C','CLASS_D','CLASS_E2','CLASS_E3','CLASS_E4')"
    for f in arcgis_query("Class_Airspace", bbox, where=where,
                          out_fields="NAME,CLASS,LOCAL_TYPE,LOWER_VAL,LOWER_DESC,UPPER_VAL,UPPER_DESC",
                          simplify=simplify_for(bbox)):
        p = f.get("properties") or {}
        kind = p.get("LOCAL_TYPE") or ""
        color, dash = CLASS_STYLE.get(kind, ("#2563eb", None))
        name = (p.get("NAME") or f"Class {p.get('CLASS')}").title().replace("Class E2", "Class E (surface)")
        lower = "surface" if not p.get("LOWER_VAL") else ft(p.get("LOWER_VAL")) + " MSL"
        upper = ft(p.get("UPPER_VAL")) + " MSL" if (p.get("UPPER_VAL") or 0) > 0 else "the class above"
        detail = (f"Class {p.get('CLASS')} airspace from {lower} to {upper}. Part 107 flights here need FAA "
                  "authorization (LAANC or DroneZone).")
        for ring in geojson_rings(f.get("geometry")):
            out.append(Feature("class", [ring], name, detail, color, None, dash))
    return out


SUA_TYPES = {"P": "Prohibited area", "R": "Restricted area", "W": "Warning area", "A": "Alert area",
             "MOA": "Military operations area", "D": "Danger area"}


def fetch_sua(bbox, zoom) -> list[Feature]:
    out = []
    for f in arcgis_query("Special_Use_Airspace", bbox, out_fields="NAME,TYPE_CODE,LOWER_VAL,UPPER_VAL,CONT_AGENT",
                          simplify=simplify_for(bbox)):
        p = f.get("properties") or {}
        code = p.get("TYPE_CODE") or ""
        kind = SUA_TYPES.get(code, "Special use airspace")
        color = "#b91c1c" if code in ("P", "R") else "#7c3aed"
        rule = {"P": "Flight is prohibited.", "R": "Flight is not allowed when the area is active unless the "
                "controlling agency approves."}.get(code, "Check whether it is active before flying.")
        detail = f"{kind} from {ft(p.get('LOWER_VAL'))} to {ft(p.get('UPPER_VAL'))}. {rule}"
        for ring in geojson_rings(f.get("geometry")):
            out.append(Feature("sua", [ring], p.get("NAME") or kind, detail, color, color if code in ("P", "R") else None,
                               None if code in ("P", "R") else (4, 3)))
    return out


def fetch_natsec(bbox, zoom) -> list[Feature]:
    out = []
    for f in arcgis_query("Part_Time_National_Security_UAS_Flight_Restrictions", bbox,
                          out_fields="Facility,Base,Reason,Floor,Ceiling,ALERTTIME", simplify=simplify_for(bbox)):
        p = f.get("properties") or {}
        name = p.get("Facility") or p.get("Base") or "National security UAS flight restriction"
        when = f" Active: {p['ALERTTIME']}." if p.get("ALERTTIME") else ""
        detail = (f"National security UAS flight restriction (part-time). {p.get('Reason') or ''}{when} "
                  "Drone flights are not allowed while it is active.").replace("  ", " ")
        for ring in geojson_rings(f.get("geometry")):
            out.append(Feature("natsec", [ring], name, detail, "#7f1d1d", "#7f1d1d"))
    for f in arcgis_query("National_Defense_Airspace_TFR_Areas", bbox, out_fields="NAME,TYPE_CODE,CITY,STATE",
                          simplify=simplify_for(bbox)):
        p = f.get("properties") or {}
        detail = "National defense airspace. Drone flights here are restricted; check the related NOTAM."
        for ring in geojson_rings(f.get("geometry")):
            out.append(Feature("natsec", [ring], p.get("NAME") or "National defense airspace", detail,
                               "#7f1d1d", "#7f1d1d"))
    return out


_tfr_cache: dict = {"time": 0.0, "features": None}
_tfr_lock = threading.Lock()


def tfr_link(notam_key: str) -> str:
    """'6/5945-1-FDC-F' -> the tfr.faa.gov details page."""
    number = (notam_key or "").split("-")[0].replace("/", "_")
    return f"https://tfr.faa.gov/tfr3/?page=detail_{number}" if number else "https://tfr.faa.gov/"


def fetch_tfr(bbox, zoom) -> list[Feature]:
    with _tfr_lock:
        if _tfr_cache["features"] is None or time.monotonic() - _tfr_cache["time"] > TFR_CACHE_S:
            r = requests.get(TFR_URL, headers=HEADERS, timeout=TIMEOUT_S)
            r.raise_for_status()
            features = []
            for f in r.json().get("features", []):
                p = f.get("properties") or {}
                notam = p.get("NOTAM_KEY") or ""
                title = p.get("TITLE") or "Temporary flight restriction"
                legal = (p.get("LEGAL") or "").replace("_", " ").title()
                detail = (f"NOTAM {notam.split('-')[0]}" + (f" · {legal}" if legal else "") +
                          ". Read the NOTAM for times and altitudes before flying nearby.")
                for ring in geojson_rings(f.get("geometry")):
                    features.append(Feature("tfr", [ring], title, detail, "#dc2626", "#dc2626", link=tfr_link(notam)))
            _tfr_cache.update(time=time.monotonic(), features=features)
        features = _tfr_cache["features"]
    s, w, n, e = bbox
    return [f for f in features if any(s <= lat <= n and w <= lon <= e for ring in f.rings for lat, lon in ring)
            or any(f.contains(lat, lon) for lat, lon in ((s, w), (n, e), ((s + n) / 2, (w + e) / 2)))]


LAYERS: dict[str, Layer] = {
    "tfr": Layer("tfr", "TFRs (temporary flight restrictions)", "TFR", "#dc2626", 4, fetch_tfr),
    "uasfm": Layer("uasfm", "UAS Facility Map ceilings (LAANC)", "UAS Facility Map (ft)", "#f59e0b", 11, fetch_uasfm),
    "class": Layer("class", "Controlled airspace (Class B, C, D, E surface)", "Controlled airspace", "#2563eb", 7,
                   fetch_class),
    "sua": Layer("sua", "Special use airspace (prohibited, restricted, MOA)", "Special use airspace", "#b91c1c", 6,
                 fetch_sua),
    "natsec": Layer("natsec", "National security UAS restrictions", "National security", "#7f1d1d", 6, fetch_natsec),
}


def whats_here(lat: float, lon: float) -> tuple[list[Feature], list[str]]:
    """Every FAA layer at a point (whether or not it is switched on). Returns (features, errors)."""
    d = 0.0005
    bbox = (lat - d, lon - d, lat + d, lon + d)
    found, errors = [], []
    for layer in LAYERS.values():
        try:
            found += [f for f in layer.fetch(bbox, 18) if f.contains(lat, lon)]
        except Exception as exc:  # offline or service error: say which layer could not be checked
            errors.append(f"{layer.name}: {short_error(exc)}")
    return found, errors


def is_busy(message: str) -> bool:
    return "too many requests" in (message or "").lower() or "429" in (message or "")


def short_error(exc: Exception) -> str:
    if is_busy(str(exc)):
        return "the FAA service is busy; trying again in a few minutes"
    if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code == 429:
        return "the FAA service is busy; trying again in a few minutes"
    if isinstance(exc, requests.ConnectionError):
        return "no internet connection"
    if isinstance(exc, requests.Timeout):
        return "the FAA service did not answer"
    return str(exc)[:80] or exc.__class__.__name__


# --------------------------------------------------------------------------
# Sectional tiles closer than zoom 12: enlarge the zoom-12 tile
# --------------------------------------------------------------------------

_parent_tiles: dict = {}
_parent_lock = threading.Lock()


def sectional_tile(zoom: int, x: int, y: int):
    """A file-like PNG for sectional tile (zoom, x, y); above zoom 12 it is cut from the zoom-12 tile."""
    if zoom <= SECTIONAL_MAX_NATIVE_ZOOM:
        url = SECTIONAL_TILES.replace("{z}", str(zoom)).replace("{x}", str(x)).replace("{y}", str(y))
        return io.BytesIO(requests.get(url, headers=HEADERS, timeout=TIMEOUT_S).content)
    shift = zoom - SECTIONAL_MAX_NATIVE_ZOOM
    px, py = x >> shift, y >> shift
    key = (px, py)
    with _parent_lock:
        parent = _parent_tiles.get(key)
    if parent is None:
        url = SECTIONAL_TILES.replace("{z}", str(SECTIONAL_MAX_NATIVE_ZOOM)).replace("{x}", str(px)).replace("{y}", str(py))
        parent = Image.open(io.BytesIO(requests.get(url, headers=HEADERS, timeout=TIMEOUT_S).content)).convert("RGB")
        with _parent_lock:
            if len(_parent_tiles) > 64:
                _parent_tiles.pop(next(iter(_parent_tiles)))
            _parent_tiles[key] = parent
    size = parent.width >> shift
    ox, oy = (x - (px << shift)) * size, (y - (py << shift)) * size
    tile = parent.crop((ox, oy, ox + size, oy + size)).resize((256, 256), Image.BILINEAR)
    out = io.BytesIO()
    tile.save(out, "PNG")
    out.seek(0)
    return out
