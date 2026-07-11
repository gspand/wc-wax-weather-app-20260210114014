import json
from pathlib import Path
from collections import defaultdict

from config import Config
from bikepacking.database import get_connection, init_db
from bikepacking.garmin_client import GarminClient


COLORS = [
    "#e53935",
    "#1e88e5",
    "#43a047",
    "#8e44ad",
    "#fb8c00",
    "#00acc1",
    "#f44336",
    "#3f51b5",
    "#8bc34a",
    "#009688",
    "#ff5722",
    "#673ab7",
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


def _points_to_geojson(points, stage_id=None):
    if not points:
        return {"type": "FeatureCollection", "features": []}
    coords = [[lon, lat] for lat, lon in points]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"stage_id": stage_id},
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        ],
    }


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


def _get_or_create_tour(name, start_date, description="Import aus Garmin"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tours ORDER BY id LIMIT 1")
    current = cursor.fetchone()
    if current:
        tour_id = current["id"]
        cursor.execute(
            "UPDATE tours SET name = ?, start_date = ?, description = ? WHERE id = ?",
            (name, start_date, description, tour_id),
        )
        conn.commit()
        conn.close()
        return tour_id

    cursor.execute(
        "INSERT INTO tours (name, start_date, description) VALUES (?, ?, ?)",
        (name, start_date, description),
    )
    tour_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return tour_id


def import_from_garmin(tour_name="Garmin Bikepacking Tour"):
    client = GarminClient()
    activities = client.import_activities()
    if not activities:
        raise RuntimeError("Keine passenden Garmin-Aktivitäten gefunden.")

    grouped = defaultdict(list)
    for activity in activities:
        key = activity.get("startTimeLocal", "")[:10]
        if key:
            grouped[key].append(activity)

    ordered_days = sorted(grouped.keys())
    tour_id = _get_or_create_tour(tour_name, client.start_date)

    conn = get_connection()
    cursor = conn.cursor()

    for idx, day in enumerate(ordered_days):
        day_activities = grouped[day]
        points = []
        activity_ids = []
        for activity in day_activities:
            activity_id = str(activity.get("activityId", ""))
            if activity_id:
                activity_ids.append(activity_id)
            points.extend(client.get_track_points(activity.get("activityId")))

        distance = sum(float(a.get("distance") or 0.0) for a in day_activities) / 1000.0
        elevation = sum(float(a.get("elevationGain") or 0.0) for a in day_activities)
        moving = int(sum(float(a.get("movingDuration") or 0.0) for a in day_activities))
        elapsed = int(sum(float(a.get("elapsedDuration") or 0.0) for a in day_activities))
        avg_hr_values = [float(a.get("averageHR") or 0) for a in day_activities if a.get("averageHR")]
        max_hr_values = [float(a.get("maxHR") or 0) for a in day_activities if a.get("maxHR")]
        avg_power_values = [float(a.get("averagePower") or 0) for a in day_activities if a.get("averagePower")]
        np_values = [float(a.get("normPower") or a.get("normalizedPower") or 0) for a in day_activities if a.get("normPower") or a.get("normalizedPower")]
        load_score = sum(float(a.get("trainingStressScore") or 0.0) for a in day_activities)

        stage_title = day_activities[0].get("activityName") or f"Etappe {idx + 1}"
        color = COLORS[idx % len(COLORS)]
        activity_key = ",".join(activity_ids)
        track_geojson = json.dumps(_points_to_geojson(points))

        cursor.execute(
            "SELECT id, diary_text, rating FROM stages WHERE garmin_activity_id = ? LIMIT 1",
            (activity_key,),
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "UPDATE stages SET tour_id = ?, date = ?, title = ?, distance = ?, elevation_gain = ?, moving_time = ?, elapsed_time = ?, average_hr = ?, max_hr = ?, average_power = ?, normalized_power = ?, load_score = ?, color = ?, track_geojson = ? WHERE id = ?",
                (
                    tour_id,
                    day,
                    stage_title,
                    round(distance, 1),
                    round(elevation),
                    moving,
                    elapsed,
                    round(sum(avg_hr_values) / len(avg_hr_values), 1) if avg_hr_values else None,
                    max(max_hr_values) if max_hr_values else None,
                    round(sum(avg_power_values) / len(avg_power_values), 1) if avg_power_values else None,
                    round(sum(np_values) / len(np_values), 1) if np_values else None,
                    round(load_score, 1),
                    color,
                    track_geojson,
                    existing["id"],
                ),
            )
        else:
            cursor.execute(
                "INSERT INTO stages (tour_id, garmin_activity_id, date, title, distance, elevation_gain, moving_time, elapsed_time, average_hr, max_hr, average_power, normalized_power, load_score, color, diary_text, rating, track_geojson) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tour_id,
                    activity_key,
                    day,
                    stage_title,
                    round(distance, 1),
                    round(elevation),
                    moving,
                    elapsed,
                    round(sum(avg_hr_values) / len(avg_hr_values), 1) if avg_hr_values else None,
                    max(max_hr_values) if max_hr_values else None,
                    round(sum(avg_power_values) / len(avg_power_values), 1) if avg_power_values else None,
                    round(sum(np_values) / len(np_values), 1) if np_values else None,
                    round(load_score, 1),
                    color,
                    "",
                    "",
                    track_geojson,
                ),
            )

    conn.commit()
    conn.close()
    return len(ordered_days)


def _coerce_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _coerce_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _extract_points_from_stage(stage_data):
    points = []

    direct_points = stage_data.get("points") or stage_data.get("track_points") or []
    for point in direct_points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        lat, lon = point[0], point[1]
        if lat is None or lon is None:
            continue
        points.append([_coerce_float(lat), _coerce_float(lon)])

    if points:
        return points

    geojson = stage_data.get("track_geojson")
    if isinstance(geojson, str):
        try:
            geojson = json.loads(geojson)
        except Exception:
            geojson = None

    if isinstance(geojson, dict):
        for feature in geojson.get("features", []):
            geometry = feature.get("geometry") or {}
            if geometry.get("type") != "LineString":
                continue
            for coord in geometry.get("coordinates", []):
                if not isinstance(coord, (list, tuple)) or len(coord) < 2:
                    continue
                lon, lat = coord[0], coord[1]
                if lat is None or lon is None:
                    continue
                points.append([_coerce_float(lat), _coerce_float(lon)])
    return points


def import_from_colab_json(payload):
    if not isinstance(payload, dict):
        raise RuntimeError("Ungueltiges JSON-Format: Objekt erwartet.")

    tour_data = payload.get("tour") or {}
    tour_name = tour_data.get("name") or payload.get("tour_name") or "Colab Garmin Export"
    start_date = tour_data.get("start_date") or payload.get("start_date") or Config.GARMIN_START_DATE
    description = tour_data.get("description") or "Import aus Google Colab"

    stages = payload.get("stages")
    if not isinstance(stages, list):
        activities = payload.get("activities")
        if isinstance(activities, list):
            stages = []
            grouped = defaultdict(list)
            for activity in activities:
                key = str(activity.get("startTimeLocal") or "")[:10]
                if key:
                    grouped[key].append(activity)

            for day in sorted(grouped.keys()):
                day_items = grouped[day]
                points = []
                for item in day_items:
                    for p in item.get("track_points", []):
                        if isinstance(p, (list, tuple)) and len(p) >= 2:
                            points.append([_coerce_float(p[0]), _coerce_float(p[1])])

                stages.append(
                    {
                        "date": day,
                        "title": day_items[0].get("activityName") or f"Etappe {day}",
                        "distance": sum(_coerce_float(i.get("distance")) for i in day_items) / 1000.0,
                        "elevation_gain": sum(_coerce_float(i.get("elevationGain")) for i in day_items),
                        "moving_time": sum(_coerce_float(i.get("movingDuration")) for i in day_items),
                        "elapsed_time": sum(_coerce_float(i.get("elapsedDuration")) for i in day_items),
                        "average_hr": _coerce_float(day_items[0].get("averageHR"), None),
                        "max_hr": _coerce_float(day_items[0].get("maxHR"), None),
                        "average_power": _coerce_float(day_items[0].get("averagePower"), None),
                        "normalized_power": _coerce_float(day_items[0].get("normPower") or day_items[0].get("normalizedPower"), None),
                        "load_score": sum(_coerce_float(i.get("trainingStressScore")) for i in day_items),
                        "garmin_activity_id": ",".join(str(i.get("activityId")) for i in day_items if i.get("activityId")),
                        "track_points": points,
                    }
                )

    if not isinstance(stages, list) or not stages:
        raise RuntimeError("Ungueltiges JSON-Format: 'stages' oder 'activities' fehlt.")

    tour_id = _get_or_create_tour(tour_name, start_date, description)

    conn = get_connection()
    cursor = conn.cursor()

    imported_count = 0
    for idx, stage in enumerate(sorted(stages, key=lambda x: str(x.get("date") or ""))):
        date_value = str(stage.get("date") or "")[:10]
        if not date_value:
            continue

        stage_title = stage.get("title") or stage.get("activityName") or f"Etappe {idx + 1}"
        garmin_activity_id = str(stage.get("garmin_activity_id") or stage.get("activity_id") or "")
        color = stage.get("color") or COLORS[idx % len(COLORS)]
        points = _extract_points_from_stage(stage)
        track_geojson = json.dumps(_points_to_geojson(points))

        distance = _coerce_float(stage.get("distance"), 0.0)
        if distance > 10000:
            distance = distance / 1000.0

        cursor.execute(
            "SELECT id FROM stages WHERE garmin_activity_id = ? AND garmin_activity_id != '' LIMIT 1",
            (garmin_activity_id,),
        )
        existing = cursor.fetchone() if garmin_activity_id else None

        values = (
            tour_id,
            garmin_activity_id,
            date_value,
            stage_title,
            round(distance, 1),
            round(_coerce_float(stage.get("elevation_gain") or stage.get("elevation"), 0.0)),
            _coerce_int(stage.get("moving_time") or stage.get("movingDuration"), 0),
            _coerce_int(stage.get("elapsed_time") or stage.get("elapsedDuration"), 0),
            _coerce_float(stage.get("average_hr") or stage.get("averageHR"), None),
            _coerce_float(stage.get("max_hr") or stage.get("maxHR"), None),
            _coerce_float(stage.get("average_power") or stage.get("averagePower"), None),
            _coerce_float(stage.get("normalized_power") or stage.get("normPower"), None),
            _coerce_float(stage.get("load_score") or stage.get("trainingStressScore"), 0.0),
            color,
            track_geojson,
        )

        if existing:
            cursor.execute(
                "UPDATE stages SET tour_id = ?, garmin_activity_id = ?, date = ?, title = ?, distance = ?, elevation_gain = ?, moving_time = ?, elapsed_time = ?, average_hr = ?, max_hr = ?, average_power = ?, normalized_power = ?, load_score = ?, color = ?, track_geojson = ? WHERE id = ?",
                (*values, existing["id"]),
            )
        else:
            cursor.execute(
                "INSERT INTO stages (tour_id, garmin_activity_id, date, title, distance, elevation_gain, moving_time, elapsed_time, average_hr, max_hr, average_power, normalized_power, load_score, color, diary_text, rating, track_geojson) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?)",
                values,
            )

        imported_count += 1

    conn.commit()
    conn.close()

    if not imported_count:
        raise RuntimeError("Keine gueltigen Etappen im Colab-Export gefunden.")

    return imported_count
