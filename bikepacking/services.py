import json
import logging
from pathlib import Path

from config import Config
from bikepacking.database import get_connection, init_db

logger = logging.getLogger(__name__)


COLORS = [
    "#e53935",  # Rot
    "#ff6f00",  # Orange
    "#ffd600",  # Gelb
    "#e91e63",  # Pink
    "#1565c0",  # Dunkelblau
    "#00bcd4",  # Cyan
    "#6a1b9a",  # Lila
    "#f50057",  # Magenta
    "#0288d1",  # Hellblau
    "#ff3d00",  # Tieforange
    "#aa00ff",  # Violett
    "#00838f",  # Dunkeltürkis
]


DEMO_TOUR = {
    "name": "Dolomiten Bikepacking 2026",
    "start_date": "2026-06-27",
    "description": "Eine Demo-Tour durch die Dolomiten mit Etappen, Karte, Tagebuch und Fotos.",
}

DEMO_STAGES = [
    {
        "date": "2026-06-27",
        "title": "Graz Rennradfahren",
        "distance": 125.0,
        "elevation_gain": 1450,
        "moving_time": 19500,
        "elapsed_time": 23000,
        "average_hr": 132,
        "max_hr": 165,
        "average_power": 145,
        "normalized_power": 158,
        "load_score": 78,
        "color": "#e53935",
        "track_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"stage": 1},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [15.438, 47.070],
                            [15.450, 47.075],
                            [15.462, 47.080],
                            [15.475, 47.090],
                        ],
                    },
                }
            ],
        },
    },
    {
        "date": "2026-06-28",
        "title": "Villach Rennradfahren",
        "distance": 110.0,
        "elevation_gain": 1220,
        "moving_time": 18200,
        "elapsed_time": 21500,
        "average_hr": 136,
        "max_hr": 170,
        "average_power": 150,
        "normalized_power": 162,
        "load_score": 82,
        "color": "#1e88e5",
        "track_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"stage": 2},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [13.850, 46.616],
                            [13.860, 46.620],
                            [13.870, 46.630],
                            [13.880, 46.640],
                        ],
                    },
                }
            ],
        },
    },
    {
        "date": "2026-06-29",
        "title": "Arta Terme Rennradfahren",
        "distance": 98.0,
        "elevation_gain": 1420,
        "moving_time": 17800,
        "elapsed_time": 21000,
        "average_hr": 138,
        "max_hr": 172,
        "average_power": 153,
        "normalized_power": 165,
        "load_score": 84,
        "color": "#43a047",
        "track_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"stage": 3},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [13.140, 46.440],
                            [13.145, 46.455],
                            [13.150, 46.470],
                            [13.155, 46.485],
                        ],
                    },
                }
            ],
        },
    },
    {
        "date": "2026-06-30",
        "title": "Auronzo di Cadore Rennradfahren",
        "distance": 92.0,
        "elevation_gain": 1250,
        "moving_time": 17000,
        "elapsed_time": 20400,
        "average_hr": 134,
        "max_hr": 168,
        "average_power": 149,
        "normalized_power": 161,
        "load_score": 80,
        "color": "#8e44ad",
        "track_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"stage": 4},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [12.330, 46.575],
                            [12.340, 46.585],
                            [12.350, 46.595],
                            [12.360, 46.605],
                        ],
                    },
                }
            ],
        },
    },
    {
        "date": "2026-07-01",
        "title": "Livinallongo del Col di Lana Rennradfahren",
        "distance": 138.0,
        "elevation_gain": 1750,
        "moving_time": 21800,
        "elapsed_time": 25000,
        "average_hr": 140,
        "max_hr": 176,
        "average_power": 158,
        "normalized_power": 170,
        "load_score": 90,
        "color": "#fb8c00",
        "track_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"stage": 5},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [11.950, 46.470],
                            [11.965, 46.485],
                            [11.980, 46.500],
                            [11.995, 46.515],
                        ],
                    },
                }
            ],
        },
    },
    {
        "date": "2026-07-03",
        "title": "Innsbruck Rennradfahren",
        "distance": 84.0,
        "elevation_gain": 1100,
        "moving_time": 15800,
        "elapsed_time": 19000,
        "average_hr": 133,
        "max_hr": 168,
        "average_power": 150,
        "normalized_power": 162,
        "load_score": 79,
        "color": "#00acc1",
        "track_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"stage": 6},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [11.400, 47.270],
                            [11.410, 47.280],
                            [11.420, 47.290],
                            [11.430, 47.300],
                        ],
                    },
                }
            ],
        },
    },
    {
        "date": "2026-07-04",
        "title": "Innsbruck Rennradfahren",
        "distance": 76.0,
        "elevation_gain": 980,
        "moving_time": 14500,
        "elapsed_time": 17200,
        "average_hr": 130,
        "max_hr": 165,
        "average_power": 142,
        "normalized_power": 155,
        "load_score": 74,
        "color": "#f44336",
        "track_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"stage": 7},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [11.400, 47.270],
                            [11.420, 47.280],
                            [11.440, 47.290],
                            [11.460, 47.300],
                        ],
                    },
                }
            ],
        },
    },
    {
        "date": "2026-07-05",
        "title": "Landeck Rennradfahren",
        "distance": 102.0,
        "elevation_gain": 1320,
        "moving_time": 18500,
        "elapsed_time": 21500,
        "average_hr": 137,
        "max_hr": 171,
        "average_power": 152,
        "normalized_power": 166,
        "load_score": 85,
        "color": "#3f51b5",
        "track_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"stage": 8},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [10.488, 47.127],
                            [10.500, 47.135],
                            [10.515, 47.145],
                            [10.530, 47.155],
                        ],
                    },
                }
            ],
        },
    },
    {
        "date": "2026-07-06",
        "title": "Feldkirch Rennradfahren",
        "distance": 85.0,
        "elevation_gain": 1010,
        "moving_time": 15900,
        "elapsed_time": 18800,
        "average_hr": 134,
        "max_hr": 168,
        "average_power": 148,
        "normalized_power": 160,
        "load_score": 80,
        "color": "#8bc34a",
        "track_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"stage": 9},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [9.601, 47.238],
                            [9.620, 47.248],
                            [9.640, 47.258],
                            [9.660, 47.268],
                        ],
                    },
                }
            ],
        },
    },
    {
        "date": "2026-07-08",
        "title": "Davos Rennradfahren",
        "distance": 92.0,
        "elevation_gain": 1180,
        "moving_time": 17000,
        "elapsed_time": 20200,
        "average_hr": 136,
        "max_hr": 170,
        "average_power": 151,
        "normalized_power": 163,
        "load_score": 82,
        "color": "#009688",
        "track_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"stage": 10},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [9.838, 46.802],
                            [9.850, 46.812],
                            [9.866, 46.822],
                            [9.880, 46.832],
                        ],
                    },
                }
            ],
        },
    },
    {
        "date": "2026-07-09",
        "title": "Chiavenna Rennradfahren",
        "distance": 100.0,
        "elevation_gain": 1300,
        "moving_time": 18500,
        "elapsed_time": 22000,
        "average_hr": 139,
        "max_hr": 174,
        "average_power": 155,
        "normalized_power": 167,
        "load_score": 88,
        "color": "#ff5722",
        "track_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"stage": 11},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [9.392, 46.169],
                            [9.405, 46.180],
                            [9.420, 46.190],
                            [9.435, 46.200],
                        ],
                    },
                }
            ],
        },
    },
    {
        "date": "2026-07-10",
        "title": "Rhäzüns Rennradfahren",
        "distance": 88.0,
        "elevation_gain": 1040,
        "moving_time": 16600,
        "elapsed_time": 19800,
        "average_hr": 135,
        "max_hr": 169,
        "average_power": 149,
        "normalized_power": 161,
        "load_score": 81,
        "color": "#673ab7",
        "track_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"stage": 12},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [9.606, 46.800],
                            [9.620, 46.810],
                            [9.635, 46.820],
                            [9.650, 46.830],
                        ],
                    },
                }
            ],
        },
    },
]


def _dict_from_row(row):
    if row is None:
        return None
    item = dict(row)
    if item.get("track_geojson"):
        try:
            item["track_geojson"] = json.loads(item["track_geojson"])
        except Exception:
            item["track_geojson"] = None
    for key in ("passes", "countries"):
        if item.get(key):
            try:
                item[key] = json.loads(item[key])
            except Exception:
                item[key] = []
        else:
            item[key] = []
    return item


def create_demo_data(force=False):
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT count(*) FROM tours")
    tour_count = cursor.fetchone()[0]
    if tour_count and not force:
        conn.close()
        return

    if force:
        cursor.execute("DELETE FROM photos")
        cursor.execute("DELETE FROM stages")
        cursor.execute("DELETE FROM tours")
        conn.commit()

    cursor.execute(
        "INSERT INTO tours (name, start_date, description) VALUES (?, ?, ?)",
        (DEMO_TOUR["name"], DEMO_TOUR["start_date"], DEMO_TOUR["description"]),
    )
    tour_id = cursor.lastrowid

    for stage in DEMO_STAGES:
        cursor.execute(
            "INSERT INTO stages (tour_id, date, title, distance, elevation_gain, moving_time, elapsed_time, average_hr, max_hr, average_power, normalized_power, load_score, color, diary_text, rating, track_geojson) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tour_id,
                stage["date"],
                stage["title"],
                stage["distance"],
                stage["elevation_gain"],
                stage["moving_time"],
                stage["elapsed_time"],
                stage["average_hr"],
                stage["max_hr"],
                stage["average_power"],
                stage["normalized_power"],
                stage["load_score"],
                stage["color"],
                "",
                "",
                json.dumps(stage["track_geojson"]),
            ),
        )
    conn.commit()
    conn.close()


def get_tour():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tours ORDER BY id LIMIT 1")
    tour = _dict_from_row(cursor.fetchone())
    conn.close()
    return tour


def get_stages():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stages ORDER BY date")
    stages = [_dict_from_row(row) for row in cursor.fetchall()]
    conn.close()
    return stages


def get_stage(stage_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stages WHERE id = ?", (stage_id,))
    stage = _dict_from_row(cursor.fetchone())
    conn.close()
    return stage


def get_stage_photos(stage_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM photos WHERE stage_id = ? ORDER BY id", (stage_id,))
    photos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return photos


def get_tour_summary():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT count(*) AS stage_count, sum(distance) AS total_distance, sum(elevation_gain) AS total_elevation, sum(moving_time) AS total_moving_time FROM stages"
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {
            "stage_count": 0,
            "total_distance": 0,
            "total_elevation": 0,
            "total_moving_time": 0,
        }

    return {
        "stage_count": row["stage_count"] or 0,
        "total_distance": round(row["total_distance"] or 0, 1),
        "total_elevation": int(row["total_elevation"] or 0),
        "total_moving_time": int(row["total_moving_time"] or 0),
    }


def save_stage_diary(stage_id, diary_text):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE stages SET diary_text = ? WHERE id = ?", (diary_text, stage_id)
    )
    conn.commit()
    conn.close()


def save_stage_rating(stage_id, rating):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE stages SET rating = ? WHERE id = ?", (rating, stage_id))
    conn.commit()
    conn.close()


def save_stage_photo(stage_id, file, filename, caption):
    upload_dir = Path(Config.UPLOAD_FOLDER)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filepath = upload_dir / f"{stage_id}_{filename}"
    try:
        file.save(str(filepath))
    except Exception:
        return False

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO photos (stage_id, filename, caption) VALUES (?, ?, ?)",
        (stage_id, filepath.name, caption),
    )
    conn.commit()
    conn.close()
    return True


def get_stage_geojson(stage):
    if not stage or not stage.get("track_geojson"):
        return {"type": "FeatureCollection", "features": []}
    if isinstance(stage["track_geojson"], dict):
        return stage["track_geojson"]
    try:
        return json.loads(stage["track_geojson"])
    except Exception:
        return {"type": "FeatureCollection", "features": []}




def get_all_stages_geojson(stages):
    features = []
    for stage in stages:
        geo = get_stage_geojson(stage)
        for feature in geo.get("features", []):
            properties = feature.get("properties", {}) or {}
            properties.update(
                {
                    "stage_id": stage.get("id"),
                    "title": stage.get("title"),
                    "date": stage.get("date"),
                    "color": stage.get("color"),
                }
            )
            features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": feature.get("geometry", {}),
                }
            )
    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# Geocoding: save detected passes + countries for a stage
# ---------------------------------------------------------------------------

def save_stage_geocoding(stage_id: int, passes: list, countries: list):
    """Persist detected passes and countries (as JSON strings) for a stage."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE stages SET passes = ?, countries = ? WHERE id = ?",
        (json.dumps(passes, ensure_ascii=False), json.dumps(countries, ensure_ascii=False), stage_id),
    )
    conn.commit()
    conn.close()


def get_stage_geocoding(stage: dict) -> dict:
    """Return {'passes': [...], 'countries': [...]} from a stage dict."""
    # _dict_from_row already parses these as lists
    passes = stage.get("passes") or []
    countries = stage.get("countries") or []
    if isinstance(passes, str):
        try:
            passes = json.loads(passes)
        except Exception:
            passes = []
    if isinstance(countries, str):
        try:
            countries = json.loads(countries)
        except Exception:
            countries = []
    return {"passes": passes, "countries": countries}


# ---------------------------------------------------------------------------
# Colab / Garmin JSON import
# ---------------------------------------------------------------------------

def _build_track_geojson_from_points(track_points):
    """Convert [[lat, lon], ...] to a GeoJSON FeatureCollection."""
    if not track_points:
        return None
    coords = [[lon, lat] for lat, lon in track_points]
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


def import_from_json(json_data: dict) -> dict:
    """
    Import tour + stages from a Colab/Garmin export JSON.

    Accepted formats:
      {"tour": {...}, "stages": [...]}
      {"activities": [...]}  (with optional track_points per activity)

    Returns {"inserted": int, "skipped": int, "errors": int}.
    """
    init_db()
    counts = {"inserted": 0, "skipped": 0, "errors": 0}

    activities = []
    tour_meta = {}

    if "stages" in json_data:
        activities = json_data.get("stages", [])
        tour_meta = json_data.get("tour", {})
    elif "activities" in json_data:
        activities = json_data.get("activities", [])
    else:
        logger.warning("import_from_json: no 'stages' or 'activities' key found")
        return counts

    conn = get_connection()
    cursor = conn.cursor()

    # Upsert tour
    cursor.execute("SELECT id FROM tours ORDER BY id LIMIT 1")
    row = cursor.fetchone()
    if row:
        tour_id = row["id"]
        if tour_meta.get("name"):
            cursor.execute("UPDATE tours SET name=? WHERE id=?", (tour_meta["name"], tour_id))
    else:
        tour_name = tour_meta.get("name") or "Importierte Tour"
        start_date = tour_meta.get("start_date") or (activities[0].get("date") or activities[0].get("startTimeLocal", "")[:10] if activities else "")
        cursor.execute(
            "INSERT INTO tours (name, start_date, description) VALUES (?, ?, ?)",
            (tour_name, start_date, tour_meta.get("description", "")),
        )
        tour_id = cursor.lastrowid

    conn.commit()

    for activity in activities:
        try:
            # Normalize field names (Garmin export vs. Colab export may differ)
            date = (
                activity.get("date")
                or activity.get("startTimeLocal", "")[:10]
                or activity.get("start_date", "")[:10]
            )
            if not date:
                counts["skipped"] += 1
                continue

            title = (
                activity.get("title")
                or activity.get("activityName")
                or activity.get("name")
                or f"Etappe {date}"
            )
            distance = float(activity.get("distance") or activity.get("distanceInMeters", 0) or 0)
            if distance > 1000:  # Garmin stores in meters
                distance = round(distance / 1000, 2)

            elevation_gain = float(
                activity.get("elevation_gain")
                or activity.get("elevationGain")
                or activity.get("totalElevationGain", 0)
                or 0
            )
            moving_time = int(
                activity.get("moving_time")
                or activity.get("movingDuration")
                or activity.get("duration", 0)
                or 0
            )
            elapsed_time = int(
                activity.get("elapsed_time")
                or activity.get("duration")
                or moving_time
            )
            avg_hr = activity.get("average_hr") or activity.get("averageHR")
            max_hr = activity.get("max_hr") or activity.get("maxHR")
            avg_power = activity.get("average_power") or activity.get("avgPower")
            norm_power = activity.get("normalized_power")
            load_score = activity.get("load_score") or activity.get("trainingLoad")
            avg_speed = activity.get("average_speed") or activity.get("averageSpeed")
            max_speed = activity.get("max_speed") or activity.get("maxSpeed")
            location = activity.get("location") or activity.get("startingPoint")

            # Track GeoJSON
            track_geojson = activity.get("track_geojson")
            if not track_geojson and activity.get("track_points"):
                track_geojson = _build_track_geojson_from_points(activity["track_points"])

            # Pick a color
            cursor.execute("SELECT count(*) FROM stages WHERE tour_id=?", (tour_id,))
            n = cursor.fetchone()[0]
            color = COLORS[n % len(COLORS)]

            garmin_id = str(activity.get("activityId") or activity.get("garmin_activity_id") or "")

            # Check for duplicate
            if garmin_id:
                cursor.execute(
                    "SELECT id FROM stages WHERE tour_id=? AND garmin_activity_id=?",
                    (tour_id, garmin_id),
                )
                if cursor.fetchone():
                    counts["skipped"] += 1
                    continue

            cursor.execute(
                """INSERT INTO stages
                   (tour_id, date, title, distance, elevation_gain, moving_time, elapsed_time,
                    average_hr, max_hr, average_power, normalized_power, load_score,
                    average_speed, max_speed, location, color, track_geojson, garmin_activity_id,
                    source, diary_text, rating)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    tour_id, date, title, distance, elevation_gain, moving_time, elapsed_time,
                    avg_hr, max_hr, avg_power, norm_power, load_score,
                    avg_speed, max_speed, location, color,
                    json.dumps(track_geojson) if track_geojson else None,
                    garmin_id, "garmin", "", "",
                ),
            )
            counts["inserted"] += 1
        except Exception as exc:
            logger.error("import_from_json: error on activity: %s", exc)
            counts["errors"] += 1

    conn.commit()
    conn.close()
    return counts
