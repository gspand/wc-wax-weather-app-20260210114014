"""Colab helper: export Garmin activities + track points to JSON for app import.

Run in Colab (or local) after installing:
    pip install garminconnect curl_cffi ua-generator
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from garminconnect import Garmin


CYCLING_TYPES = {
    "cycling",
    "road_biking",
    "mountain_biking",
    "gravel_cycling",
    "bike",
}


def parse_dt(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def extract_track_points(api, activity_id):
    details = api.get_activity_details(activity_id)
    points = []

    for point in details.get("activityDetailMetrics", []):
        lat = point.get("directLatitude") if point.get("directLatitude") is not None else point.get("latitude")
        lon = point.get("directLongitude") if point.get("directLongitude") is not None else point.get("longitude")
        if lat is not None and lon is not None:
            points.append([float(lat), float(lon)])

    if points:
        return points

    poly = details.get("geoPolylineDTO", {}) or {}
    polyline_data = poly.get("polyline")
    if isinstance(polyline_data, list):
        for item in polyline_data:
            lat = item.get("lat") if item.get("lat") is not None else item.get("latitude")
            lon = item.get("lon") if item.get("lon") is not None else item.get("longitude")
            if lat is not None and lon is not None:
                points.append([float(lat), float(lon)])

    return points


def export_colab_json(email, password, start_date, output_path="bikepacking_colab_export.json", tour_name="Bikepacking Colab Export"):
    api = Garmin(email, password)
    api.login()

    start_date_dt = datetime.strptime(start_date, "%Y-%m-%d")
    activities = []
    offset = 0

    while True:
        batch = api.get_activities(offset, 100)
        if not batch:
            break
        activities.extend(batch)
        offset += len(batch)

    filtered = []
    for activity in activities:
        start_time = activity.get("startTimeLocal")
        if not start_time:
            continue
        if parse_dt(start_time) < start_date_dt:
            continue
        type_key = (activity.get("activityType") or {}).get("typeKey", "")
        if type_key not in CYCLING_TYPES:
            continue
        filtered.append(activity)

    filtered.sort(key=lambda x: x.get("startTimeLocal", ""))

    grouped = defaultdict(list)
    for activity in filtered:
        grouped[activity["startTimeLocal"][:10]].append(activity)

    stages = []
    for day in sorted(grouped.keys()):
        day_items = grouped[day]
        all_points = []
        for item in day_items:
            all_points.extend(extract_track_points(api, item.get("activityId")))

        stages.append(
            {
                "date": day,
                "title": day_items[0].get("activityName") or f"Etappe {day}",
                "garmin_activity_id": ",".join(str(i.get("activityId")) for i in day_items if i.get("activityId")),
                "distance": round(sum(float(i.get("distance") or 0.0) for i in day_items) / 1000.0, 1),
                "elevation_gain": round(sum(float(i.get("elevationGain") or 0.0) for i in day_items), 0),
                "moving_time": int(sum(float(i.get("movingDuration") or 0.0) for i in day_items)),
                "elapsed_time": int(sum(float(i.get("elapsedDuration") or 0.0) for i in day_items)),
                "average_hr": day_items[0].get("averageHR"),
                "max_hr": day_items[0].get("maxHR"),
                "average_power": day_items[0].get("averagePower"),
                "normalized_power": day_items[0].get("normPower") or day_items[0].get("normalizedPower"),
                "load_score": round(sum(float(i.get("trainingStressScore") or 0.0) for i in day_items), 1),
                "track_points": all_points,
            }
        )

    payload = {
        "tour": {
            "name": tour_name,
            "start_date": start_date,
            "description": "Export aus Google Colab",
        },
        "stages": stages,
    }

    Path(output_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path, len(stages)


if __name__ == "__main__":
    raise SystemExit("Use export_colab_json(email, password, start_date) from Colab.")
