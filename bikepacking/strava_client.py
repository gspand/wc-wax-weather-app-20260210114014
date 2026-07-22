"""
Strava API client: OAuth token management and activity fetching.

Secrets (CLIENT_ID, CLIENT_SECRET, WEBHOOK_VERIFY_TOKEN) are read
exclusively from environment variables via Config. They are never logged,
stored in files outside the database, or exposed in API responses.
"""

import logging
import time
from datetime import datetime, timezone

import requests

from config import Config
from bikepacking.database import get_connection

logger = logging.getLogger(__name__)

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

# Cycling activity types imported as bikepacking stages
BIKEPACKING_SPORT_TYPES = {
    "Ride",
    "GravelRide",
    "MountainBikeRide",
    "EBikeRide",
}


def is_configured():
    """Return True when all required Strava OAuth env vars are present."""
    return bool(
        Config.STRAVA_CLIENT_ID
        and Config.STRAVA_CLIENT_SECRET
        and Config.STRAVA_CALLBACK_URL
    )


# ---------------------------------------------------------------------------
# Token storage (single-user, stored in DB)
# ---------------------------------------------------------------------------

def _save_tokens(athlete_id, access_token, refresh_token, expires_at, scope=""):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM strava_tokens LIMIT 1")
    row = cursor.fetchone()
    if row:
        cursor.execute(
            """
            UPDATE strava_tokens
               SET athlete_id=?, access_token=?, refresh_token=?,
                   expires_at=?, scope=?, updated_at=?
             WHERE id=?
            """,
            (athlete_id, access_token, refresh_token, expires_at, scope, now, row["id"]),
        )
    else:
        cursor.execute(
            """
            INSERT INTO strava_tokens
                (athlete_id, access_token, refresh_token, expires_at, scope, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (athlete_id, access_token, refresh_token, expires_at, scope, now, now),
        )
    conn.commit()
    conn.close()


def _load_tokens():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM strava_tokens LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def delete_tokens():
    """Remove all stored Strava tokens (disconnect)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM strava_tokens")
    conn.commit()
    conn.close()
    logger.info("Strava tokens removed")


def is_connected():
    """Return True when a valid (or refreshable) Strava token exists."""
    return _load_tokens() is not None


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------

def get_authorization_url(state=""):
    """Build the Strava OAuth authorization URL."""
    params = {
        "client_id": Config.STRAVA_CLIENT_ID,
        "redirect_uri": Config.STRAVA_CALLBACK_URL,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "activity:read_all",
    }
    if state:
        params["state"] = state
    from urllib.parse import urlencode
    return f"{STRAVA_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code):
    """Exchange an OAuth authorization code for access/refresh tokens."""
    resp = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": Config.STRAVA_CLIENT_ID,
            "client_secret": Config.STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    athlete_id = str(data.get("athlete", {}).get("id", ""))
    _save_tokens(
        athlete_id=athlete_id,
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=data["expires_at"],
        scope=data.get("scope", ""),
    )
    logger.info("Strava tokens stored for athlete %s", athlete_id)
    return athlete_id


def _refresh_tokens_if_needed(tokens):
    """Refresh the access token if it expires within 60 seconds."""
    now_ts = int(time.time())
    if tokens["expires_at"] > now_ts + 60:
        return tokens

    logger.info("Refreshing Strava access token")
    resp = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": Config.STRAVA_CLIENT_ID,
            "client_secret": Config.STRAVA_CLIENT_SECRET,
            "refresh_token": tokens["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _save_tokens(
        athlete_id=tokens.get("athlete_id", ""),
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=data["expires_at"],
        scope=tokens.get("scope", ""),
    )
    logger.info("Strava token refreshed successfully")
    return _load_tokens()


def _get_valid_token():
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError("Kein Strava-Konto verbunden.")
    tokens = _refresh_tokens_if_needed(tokens)
    return tokens["access_token"]


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def _api_get(path, params=None):
    token = _get_valid_token()
    resp = requests.get(
        f"{STRAVA_API_BASE}{path}",
        headers={"Authorization": "Bearer " + token},
        params=params or {},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_activities_in_range(after_ts, before_ts):
    """
    Fetch all activities between two Unix timestamps.
    Returns a flat list of activity summary objects.
    """
    activities = []
    page = 1
    while True:
        batch = _api_get(
            "/athlete/activities",
            params={
                "after": after_ts,
                "before": before_ts,
                "per_page": 200,
                "page": page,
            },
        )
        if not batch:
            break
        activities.extend(batch)
        if len(batch) < 200:
            break
        page += 1
    return activities


def get_activity_detail(activity_id):
    """Fetch detailed data for a single Strava activity."""
    return _api_get(f"/activities/{activity_id}", params={"include_all_efforts": False})


def get_activity_streams(activity_id):
    """
    Fetch GPS + altitude streams for an activity.
    Returns a dict keyed by stream type.
    """
    try:
        data = _api_get(
            f"/activities/{activity_id}/streams",
            params={
                "keys": "latlng,altitude,time",
                "key_by_type": True,
            },
        )
        return data
    except Exception as exc:
        logger.warning("Could not fetch streams for activity %s: %s", activity_id, exc)
        return {}


def is_bikepacking_activity(activity):
    """Return True when the sport type should be imported as a bikepacking stage."""
    sport_type = activity.get("sport_type") or activity.get("type") or ""
    return sport_type in BIKEPACKING_SPORT_TYPES


def build_track_geojson(streams):
    """
    Convert Strava latlng stream to a GeoJSON FeatureCollection.
    Returns None when no GPS data is available.
    """
    latlng = streams.get("latlng", {})
    points = latlng.get("data") if isinstance(latlng, dict) else None

    altitude = streams.get("altitude", {})
    altitudes = altitude.get("data") if isinstance(altitude, dict) else None

    if not points:
        return None

    coords = []
    for i, (lat, lon) in enumerate(points):
        coord = [lon, lat]
        if altitudes and i < len(altitudes):
            coord.append(altitudes[i])
        coords.append(coord)

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        ],
    }
