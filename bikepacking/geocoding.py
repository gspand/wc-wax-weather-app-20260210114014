"""
Geocoding helpers for automatic pass and country detection.

- detect_countries(track_points):  Nominatim reverse geocoding to find country crossings.
- detect_passes(track_points):     Overpass API to find named mountain passes near the route.

Both functions accept a list of [lat, lon] coordinate pairs (or [lon, lat, alt] GeoJSON style –
the caller must pass [lat, lon]).

API policies:
  - Nominatim: max 1 req/s, User-Agent required.
  - Overpass:  public instance, free, no key needed.
"""

import logging
import time
from typing import List, Tuple

import requests

logger = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_USER_AGENT = "BikepackingDiaryApp/1.0 (self-hosted)"

# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

def _sample_track(track_points: list, max_samples: int = 40) -> list:
    """Return an evenly-spaced subsample of track_points."""
    if not track_points:
        return []
    step = max(1, len(track_points) // max_samples)
    sampled = track_points[::step]
    # always include the last point
    if track_points[-1] not in sampled:
        sampled.append(track_points[-1])
    return sampled


def _nominatim_reverse(lat: float, lon: float) -> dict:
    """Single Nominatim reverse-geocode call. Returns parsed JSON or {}."""
    try:
        r = requests.get(
            _NOMINATIM_URL,
            params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 5},
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("Nominatim error at (%s, %s): %s", lat, lon, exc)
        return {}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def detect_countries(track_points_latlon: list) -> List[str]:
    """
    Given a list of [lat, lon] points, return an ordered list of unique
    country names crossed during the stage (e.g. ["Österreich", "Italien"]).

    Queries Nominatim with a max of 20 samples (≈ 1 request per second).
    """
    sampled = _sample_track(track_points_latlon, max_samples=20)
    countries: list = []
    last_country = None

    for lat, lon in sampled:
        data = _nominatim_reverse(lat, lon)
        address = data.get("address", {})
        country = address.get("country") or address.get("country_name") or ""
        if country and country != last_country:
            if country not in countries:
                countries.append(country)
            last_country = country
        time.sleep(1.1)  # Nominatim rate-limit: 1 req/s

    return countries


def detect_passes(track_points_latlon: list) -> List[str]:
    """
    Given a list of [lat, lon] points, return a list of named mountain passes
    crossed during the stage (OSM natural=saddle or mountain_pass=yes).

    Uses a single Overpass query over the bounding box of the route.
    """
    if not track_points_latlon:
        return []

    lats = [p[0] for p in track_points_latlon]
    lons = [p[1] for p in track_points_latlon]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    # Add a small buffer (~500 m ≈ 0.005 deg)
    buf = 0.005
    bbox = f"{min_lat - buf},{min_lon - buf},{max_lat + buf},{max_lon + buf}"

    query = f"""
    [out:json][timeout:30];
    (
      node["natural"="saddle"][bbox={bbox}];
      node["mountain_pass"="yes"][bbox={bbox}];
      node["tourism"="alpine_hut"]["name"][bbox={bbox}];
    );
    out body;
    """
    # Fix the bbox syntax for Overpass
    query = f"""
    [out:json][timeout:30];
    (
      node["natural"="saddle"]({min_lat - buf},{min_lon - buf},{max_lat + buf},{max_lon + buf});
      node["mountain_pass"="yes"]({min_lat - buf},{min_lon - buf},{max_lat + buf},{max_lon + buf});
    );
    out body;
    """

    try:
        r = requests.post(
            _OVERPASS_URL,
            data=query,
            headers={"User-Agent": _USER_AGENT},
            timeout=35,
        )
        r.raise_for_status()
        elements = r.json().get("elements", [])
    except Exception as exc:
        logger.warning("Overpass error: %s", exc)
        return []

    # Filter: only include nodes that are within ~300 m of at least one track point
    passes = []
    for el in elements:
        name = el.get("tags", {}).get("name") or el.get("tags", {}).get("name:de") or ""
        if not name:
            continue
        el_lat, el_lon = el.get("lat", 0), el.get("lon", 0)
        # Check proximity: within ~0.003 deg (~300 m) of any track point
        near = any(
            abs(pt[0] - el_lat) < 0.003 and abs(pt[1] - el_lon) < 0.003
            for pt in track_points_latlon
        )
        if near and name not in passes:
            passes.append(name)

    return passes


def extract_latlon_from_geojson(geojson: dict) -> List[Tuple[float, float]]:
    """
    Extract [lat, lon] pairs from a GeoJSON FeatureCollection with LineString features.
    GeoJSON stores coordinates as [lon, lat, (alt)].
    """
    points = []
    if not geojson:
        return points
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry", {})
        if geometry.get("type") == "LineString":
            for coord in geometry.get("coordinates", []):
                if len(coord) >= 2:
                    lon, lat = coord[0], coord[1]
                    points.append((lat, lon))
    return points


def enrich_stage_geocoding(stage: dict) -> dict:
    """
    Given a stage dict (with optional track_geojson), detect countries and passes.
    Returns a dict with keys 'countries' (list[str]) and 'passes' (list[str]).
    """
    import json as _json

    geojson = stage.get("track_geojson")
    if isinstance(geojson, str):
        try:
            geojson = _json.loads(geojson)
        except Exception:
            geojson = None

    if not geojson:
        return {"countries": [], "passes": []}

    points = extract_latlon_from_geojson(geojson)
    if not points:
        return {"countries": [], "passes": []}

    logger.info(
        "Geocoding stage '%s' (%d track points)...", stage.get("title", "?"), len(points)
    )

    passes = detect_passes(list(points))
    countries = detect_countries(list(points))

    logger.info("  → Passes: %s | Countries: %s", passes, countries)
    return {"countries": countries, "passes": passes}
