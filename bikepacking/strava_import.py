"""
Strava import logic: activity mapping, rest-day management, idempotent upsert.

Design goals
------------
* Never create duplicate stages: unique key is (source='strava', external_activity_id).
* Detect manually-imported activities that match a Strava activity by date + start
  time + duration + distance; log uncertain matches instead of auto-merging.
* Create rest-day stages for every calendar day within the tour date range that
  has no activity.  Uses the local date from the Strava activity's timezone.
* Rest days are automatically promoted / demoted as activities are added / removed.
* Never create rest days outside the tour's explicitly defined date range.
"""

import json
import logging
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from bikepacking.database import get_connection
from bikepacking import strava_client as sc

logger = logging.getLogger(__name__)

COLORS = [
    "#e53935", "#ff6f00", "#ffd600", "#e91e63",
    "#1565c0", "#00bcd4", "#6a1b9a", "#f50057",
    "#0288d1", "#ff3d00", "#aa00ff", "#00838f",
]

SOURCE_STRAVA = "strava"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _local_date_from_activity(activity):
    """
    Return the local calendar date (YYYY-MM-DD) for a Strava activity.
    Prefers `start_date_local`; falls back to UTC start_date.
    """
    local_str = activity.get("start_date_local") or activity.get("start_date")
    if not local_str:
        return None
    try:
        return local_str[:10]
    except Exception:
        return None


def _map_activity_to_stage(activity, detail, streams, tour_id, color):
    """
    Map a Strava activity (summary + detail + streams) to a stages-row dict.
    """
    sport_type = activity.get("sport_type") or activity.get("type") or "Ride"
    title = activity.get("name") or sport_type
    local_date = _local_date_from_activity(activity)
    distance_m = float(activity.get("distance") or 0.0)
    distance_km = round(distance_m / 1000.0, 2)
    elevation_gain = float(activity.get("total_elevation_gain") or 0.0)
    moving_time = int(activity.get("moving_time") or 0)
    elapsed_time = int(activity.get("elapsed_time") or 0)
    avg_speed_ms = float(activity.get("average_speed") or 0.0)
    max_speed_ms = float(activity.get("max_speed") or 0.0)
    avg_speed_kmh = round(avg_speed_ms * 3.6, 2) if avg_speed_ms else None
    max_speed_kmh = round(max_speed_ms * 3.6, 2) if max_speed_ms else None

    avg_hr = activity.get("average_heartrate")
    max_hr = activity.get("max_heartrate")
    avg_cadence = activity.get("average_cadence")
    # Temperature comes from detail (weather_summary or detail field)
    temperature = None
    if detail:
        temperature = (
            detail.get("average_temp")
            or detail.get("device_watts")
            and None  # guard against power field misread
        )
        if temperature is None:
            temperature = detail.get("average_temp")

    avg_power = None
    if detail:
        avg_power = detail.get("average_watts")

    track_geojson = sc.build_track_geojson(streams)

    return {
        "tour_id": tour_id,
        "source": SOURCE_STRAVA,
        "external_activity_id": str(activity["id"]),
        "date": local_date,
        "title": title,
        "distance": distance_km,
        "elevation_gain": round(elevation_gain),
        "moving_time": moving_time,
        "elapsed_time": elapsed_time,
        "average_hr": avg_hr,
        "max_hr": max_hr,
        "average_power": avg_power,
        "average_speed": avg_speed_kmh,
        "max_speed": max_speed_kmh,
        "average_cadence": avg_cadence,
        "temperature": temperature,
        "color": color,
        "is_rest_day": 0,
        "track_geojson": json.dumps(track_geojson) if track_geojson else None,
    }


# ---------------------------------------------------------------------------
# Duplicate detection for manually-imported stages
# ---------------------------------------------------------------------------

def _check_manual_duplicate(cursor, local_date, moving_time, distance_km):
    """
    Check whether a manually imported stage closely matches a Strava activity.
    Returns the existing stage id or None.  Logs uncertain matches; never
    auto-merges to avoid data loss.
    """
    cursor.execute(
        """
        SELECT id, title, moving_time, distance
          FROM stages
         WHERE date = ?
           AND (source IS NULL OR source = 'manual')
           AND is_rest_day = 0
        """,
        (local_date,),
    )
    candidates = cursor.fetchall()
    for row in candidates:
        dt_match = abs((row["moving_time"] or 0) - moving_time) < 120  # ±2 min
        dist_match = abs((row["distance"] or 0) - distance_km) < 1.0    # ±1 km
        if dt_match and dist_match:
            logger.warning(
                "Possible duplicate: manual stage id=%s '%s' on %s "
                "matches Strava activity (distance=%.1f km, moving_time=%ds). "
                "Skipping auto-merge.",
                row["id"], row["title"], local_date, distance_km, moving_time,
            )
            return row["id"]
    return None


# ---------------------------------------------------------------------------
# Upsert a single Strava activity
# ---------------------------------------------------------------------------

def upsert_strava_stage(activity, tour_id, color_index=0):
    """
    Insert or update a single Strava activity as a stage.
    Returns ('inserted'|'updated'|'skipped', stage_id).
    Raises ValueError for non-bikepacking activities.
    """
    if not sc.is_bikepacking_activity(activity):
        sport = activity.get("sport_type") or activity.get("type")
        raise ValueError(f"Sport type '{sport}' is not a bikepacking activity")

    external_id = str(activity["id"])
    local_date = _local_date_from_activity(activity)
    color = COLORS[color_index % len(COLORS)]

    # Fetch detail + streams for rich data
    try:
        detail = sc.get_activity_detail(external_id)
    except Exception as exc:
        logger.warning("Could not fetch detail for activity %s: %s", external_id, exc)
        detail = {}

    try:
        streams = sc.get_activity_streams(external_id)
    except Exception as exc:
        logger.warning("Could not fetch streams for activity %s: %s", external_id, exc)
        streams = {}

    stage_data = _map_activity_to_stage(activity, detail, streams, tour_id, color)

    conn = get_connection()
    cursor = conn.cursor()

    # Check for existing Strava stage (idempotent key)
    cursor.execute(
        "SELECT id FROM stages WHERE source=? AND external_activity_id=? LIMIT 1",
        (SOURCE_STRAVA, external_id),
    )
    existing = cursor.fetchone()

    if existing:
        _do_update(cursor, stage_data, existing["id"])
        conn.commit()
        conn.close()
        logger.info("Updated Strava stage %s (stage id=%s)", external_id, existing["id"])
        return "updated", existing["id"]

    # Check for manual duplicate
    dup_id = _check_manual_duplicate(
        cursor, local_date, stage_data["moving_time"], stage_data["distance"]
    )
    if dup_id is not None:
        conn.close()
        return "skipped", dup_id

    stage_id = _do_insert(cursor, stage_data)
    conn.commit()
    conn.close()
    logger.info("Inserted Strava stage %s as stage id=%s", external_id, stage_id)
    return "inserted", stage_id


def _do_insert(cursor, data):
    cursor.execute(
        """
        INSERT INTO stages
            (tour_id, source, external_activity_id, date, title,
             distance, elevation_gain, moving_time, elapsed_time,
             average_hr, max_hr, average_power, average_speed, max_speed,
             average_cadence, temperature, color, diary_text, rating,
             is_rest_day, track_geojson)
        VALUES
            (:tour_id, :source, :external_activity_id, :date, :title,
             :distance, :elevation_gain, :moving_time, :elapsed_time,
             :average_hr, :max_hr, :average_power, :average_speed, :max_speed,
             :average_cadence, :temperature, :color, '', '',
             :is_rest_day, :track_geojson)
        """,
        data,
    )
    return cursor.lastrowid


def _do_update(cursor, data, stage_id):
    cursor.execute(
        """
        UPDATE stages
           SET tour_id=:tour_id, date=:date, title=:title,
               distance=:distance, elevation_gain=:elevation_gain,
               moving_time=:moving_time, elapsed_time=:elapsed_time,
               average_hr=:average_hr, max_hr=:max_hr,
               average_power=:average_power, average_speed=:average_speed,
               max_speed=:max_speed, average_cadence=:average_cadence,
               temperature=:temperature, color=:color,
               is_rest_day=0, track_geojson=:track_geojson
         WHERE id=:stage_id
        """,
        {**data, "stage_id": stage_id},
    )


# ---------------------------------------------------------------------------
# Rest-day management
# ---------------------------------------------------------------------------

def _iter_date_range(start_date_str, end_date_str):
    """Yield each date (as string YYYY-MM-DD) from start to end inclusive."""
    start = date.fromisoformat(start_date_str)
    end = date.fromisoformat(end_date_str)
    current = start
    while current <= end:
        yield str(current)
        current += timedelta(days=1)


def rebuild_rest_days(tour_id):
    """
    Rebuild rest-day stages for *tour_id*.

    For every calendar day within [tour.start_date, tour.end_date]:
    - If at least one non-rest-day stage exists → ensure no rest-day exists.
    - If no non-rest-day stage exists → ensure exactly one rest-day exists.

    Stages outside the tour date range are not touched.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT start_date, end_date FROM tours WHERE id=?", (tour_id,)
    )
    tour = cursor.fetchone()
    conn.close()

    if not tour or not tour["start_date"] or not tour["end_date"]:
        logger.debug("rebuild_rest_days: tour %s has no date range, skipping", tour_id)
        return

    start = tour["start_date"]
    end = tour["end_date"]
    if start > end:
        logger.warning("rebuild_rest_days: start_date > end_date for tour %s", tour_id)
        return

    for day in _iter_date_range(start, end):
        _ensure_rest_day_for(tour_id, day)


def _ensure_rest_day_for(tour_id, day):
    """Create or remove rest-day stage for a single calendar day."""
    conn = get_connection()
    cursor = conn.cursor()

    # Count active (non-rest-day) stages on this day
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt FROM stages
         WHERE tour_id=? AND date=? AND is_rest_day=0
        """,
        (tour_id, day),
    )
    active_count = cursor.fetchone()["cnt"]

    if active_count > 0:
        # Activity exists → remove any rest-day stage for this day
        cursor.execute(
            "DELETE FROM stages WHERE tour_id=? AND date=? AND is_rest_day=1",
            (tour_id, day),
        )
        if cursor.rowcount:
            logger.info("Removed rest day for tour %s on %s (activity present)", tour_id, day)
    else:
        # No activity → ensure a rest-day stage exists
        cursor.execute(
            "SELECT id FROM stages WHERE tour_id=? AND date=? AND is_rest_day=1 LIMIT 1",
            (tour_id, day),
        )
        if not cursor.fetchone():
            cursor.execute(
                """
                INSERT INTO stages
                    (tour_id, date, title, distance, elevation_gain,
                     moving_time, elapsed_time, is_rest_day,
                     source, diary_text, rating)
                VALUES (?, ?, ?, 0, 0, 0, 0, 1, 'rest', '', '')
                """,
                (tour_id, day, f"Ruhetag {day}"),
            )
            logger.info("Created rest day for tour %s on %s", tour_id, day)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Initial bulk import
# ---------------------------------------------------------------------------

def import_strava_for_tour(tour_id, start_date_str, end_date_str):
    """
    Fetch all bikepacking activities from Strava within [start_date, end_date]
    and import them into the given tour.

    Also updates tour.end_date and calls rebuild_rest_days.

    Returns a dict with counts: inserted, updated, skipped, errors.
    """
    import calendar

    # Convert dates to Unix timestamps (beginning and end of day, UTC)
    start_dt = datetime.fromisoformat(start_date_str).replace(
        hour=0, minute=0, second=0, tzinfo=timezone.utc
    )
    end_dt = datetime.fromisoformat(end_date_str).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )
    after_ts = int(start_dt.timestamp())
    before_ts = int(end_dt.timestamp())

    logger.info(
        "Fetching Strava activities for tour %s from %s to %s",
        tour_id, start_date_str, end_date_str,
    )
    activities = sc.get_activities_in_range(after_ts, before_ts)
    bikepacking = [a for a in activities if sc.is_bikepacking_activity(a)]

    logger.info(
        "Found %d total / %d bikepacking activities in range",
        len(activities), len(bikepacking),
    )

    counts = {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0}
    for idx, activity in enumerate(bikepacking):
        try:
            action, _ = upsert_strava_stage(activity, tour_id, color_index=idx)
            counts[action] += 1
        except Exception as exc:
            counts["errors"] += 1
            logger.error(
                "Error importing Strava activity %s: %s",
                activity.get("id"), exc,
            )

    # Update tour date range
    _update_tour_dates(tour_id, start_date_str, end_date_str)

    # Rebuild rest days for the full range
    rebuild_rest_days(tour_id)

    logger.info("Strava import complete: %s", counts)
    return counts


def _update_tour_dates(tour_id, start_date_str, end_date_str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE tours SET start_date=?, end_date=? WHERE id=?",
        (start_date_str, end_date_str, tour_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Webhook event handlers
# ---------------------------------------------------------------------------

def handle_webhook_create(activity_id, owner_id):
    """Process a Strava 'create' webhook event."""
    logger.info("Webhook create: activity %s owner %s", activity_id, owner_id)
    try:
        activity = sc.get_activity_detail(str(activity_id))
    except Exception as exc:
        logger.error("Could not fetch activity %s for webhook create: %s", activity_id, exc)
        return

    if not sc.is_bikepacking_activity(activity):
        logger.info(
            "Webhook create: activity %s is not a bikepacking type (%s), skipping",
            activity_id, activity.get("sport_type"),
        )
        return

    tour_id = _get_tour_id()
    if tour_id is None:
        logger.warning("Webhook create: no tour found, skipping activity %s", activity_id)
        return

    # Check activity date is within tour range
    local_date = _local_date_from_activity(activity)
    if not _date_within_tour(tour_id, local_date):
        logger.info(
            "Webhook create: activity %s on %s is outside tour range, skipping",
            activity_id, local_date,
        )
        return

    try:
        action, stage_id = upsert_strava_stage(activity, tour_id, color_index=0)
        logger.info("Webhook create: activity %s → %s (stage %s)", activity_id, action, stage_id)
        rebuild_rest_days(tour_id)
    except Exception as exc:
        logger.error("Webhook create failed for activity %s: %s", activity_id, exc)


def handle_webhook_update(activity_id, owner_id, updates):
    """Process a Strava 'update' webhook event."""
    logger.info("Webhook update: activity %s owner %s", activity_id, owner_id)
    try:
        activity = sc.get_activity_detail(str(activity_id))
    except Exception as exc:
        logger.error("Could not fetch activity %s for webhook update: %s", activity_id, exc)
        return

    if not sc.is_bikepacking_activity(activity):
        logger.info(
            "Webhook update: activity %s is not bikepacking type, skipping",
            activity_id,
        )
        return

    tour_id = _get_tour_id()
    if tour_id is None:
        return

    try:
        action, stage_id = upsert_strava_stage(activity, tour_id, color_index=0)
        logger.info("Webhook update: activity %s → %s (stage %s)", activity_id, action, stage_id)
        rebuild_rest_days(tour_id)
    except Exception as exc:
        logger.error("Webhook update failed for activity %s: %s", activity_id, exc)


def handle_webhook_delete(activity_id, owner_id):
    """Process a Strava 'delete' webhook event."""
    logger.info("Webhook delete: activity %s owner %s", activity_id, owner_id)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, date, tour_id FROM stages WHERE source=? AND external_activity_id=? LIMIT 1",
        (SOURCE_STRAVA, str(activity_id)),
    )
    row = cursor.fetchone()
    if not row:
        logger.info("Webhook delete: activity %s not found locally, nothing to do", activity_id)
        conn.close()
        return

    stage_id = row["id"]
    local_date = row["date"]
    tour_id = row["tour_id"]

    # Delete associated photos
    cursor.execute("DELETE FROM photos WHERE stage_id=?", (stage_id,))
    cursor.execute("DELETE FROM stages WHERE id=?", (stage_id,))
    conn.commit()
    conn.close()
    logger.info("Webhook delete: removed stage %s (activity %s)", stage_id, activity_id)

    # Rebuild rest day status for affected day
    _ensure_rest_day_for(tour_id, local_date)


def handle_webhook_deauthorize(athlete_id):
    """Process a Strava deauthorization event."""
    logger.info("Strava deauthorization for athlete %s – removing tokens", athlete_id)
    sc.delete_tokens()
    # Existing travel data is intentionally preserved; the user can decide
    # what to do with it after reconnecting or manually.


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_tour_id():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tours ORDER BY id LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row["id"] if row else None


def _date_within_tour(tour_id, local_date):
    if not local_date:
        return False
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT start_date, end_date FROM tours WHERE id=?", (tour_id,))
    tour = cursor.fetchone()
    conn.close()
    if not tour or not tour["start_date"]:
        return True  # no range set → accept
    if tour["start_date"] and local_date < tour["start_date"]:
        return False
    if tour["end_date"] and local_date > tour["end_date"]:
        return False
    return True
