from datetime import datetime
import os
from pathlib import Path
from xml.etree import ElementTree as ET

from config import Config
from bikepacking.runtime_settings import load_runtime_settings


CYCLING_TYPES = {
    "cycling",
    "road_biking",
    "mountain_biking",
    "gravel_cycling",
    "bike",
}


class GarminClient:
    def __init__(self):
        runtime = load_runtime_settings()
        self.username = os.environ.get(
            "GARMIN_USERNAME",
            runtime.get("GARMIN_USERNAME") or Config.GARMIN_USERNAME,
        )
        self.password = os.environ.get(
            "GARMIN_PASSWORD",
            runtime.get("GARMIN_PASSWORD") or Config.GARMIN_PASSWORD,
        )
        self.start_date = os.environ.get(
            "GARMIN_START_DATE",
            runtime.get("GARMIN_START_DATE") or Config.GARMIN_START_DATE,
        )
        self.token_store_path = Path(Config.DATA_DIR) / "garmin_tokens"
        self.api = None

    def is_configured(self):
        return bool(self.username and self.password)

    def login(self):
        if not self.is_configured():
            raise RuntimeError("Garmin-Anmeldedaten fehlen. Bitte GARMIN_USERNAME und GARMIN_PASSWORD setzen.")

        try:
            from garminconnect import Garmin
        except ImportError as exc:
            raise RuntimeError("Paket 'garminconnect' fehlt. Bitte requirements installieren.") from exc

        self.api = Garmin(self.username, self.password)

        # Try cached tokens first (avoids fresh OAuth which triggers Garmin 429).
        token_dir = str(self.token_store_path)
        if self.token_store_path.exists():
            try:
                self.api.login(tokenstore=token_dir)
                return True
            except Exception:
                pass  # Token expired or invalid – fall through to credential login.

        self.api.login()

        try:
            self.token_store_path.mkdir(parents=True, exist_ok=True)
            self.api.garth.dump(token_dir)
        except Exception:
            pass
        return True

    def _parse_local_time(self, value):
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

    def get_activities(self):
        if self.api is None:
            self.login()

        activities = []
        start = 0
        while True:
            batch = self.api.get_activities(start, 100)
            if not batch:
                break
            activities.extend(batch)
            start += len(batch)
        return activities

    def _activity_is_cycling(self, activity):
        type_key = (activity.get("activityType") or {}).get("typeKey", "")
        return type_key in CYCLING_TYPES

    def _extract_track_from_metrics(self, details):
        points = []
        for point in details.get("activityDetailMetrics", []):
            lat = point.get("directLatitude")
            lon = point.get("directLongitude")
            if lat is None:
                lat = point.get("latitude")
            if lon is None:
                lon = point.get("longitude")
            if lat is not None and lon is not None:
                points.append([float(lat), float(lon)])
        return points

    def _extract_track_from_polyline_list(self, details):
        points = []
        poly = details.get("geoPolylineDTO", {}) or {}
        polyline_data = poly.get("polyline")
        if isinstance(polyline_data, list):
            for item in polyline_data:
                lat = item.get("lat")
                lon = item.get("lon")
                if lat is None:
                    lat = item.get("latitude")
                if lon is None:
                    lon = item.get("longitude")
                if lat is not None and lon is not None:
                    points.append([float(lat), float(lon)])
        return points

    def _extract_track_from_gpx(self, activity_id):
        points = []
        try:
            gpx = self.api.download_activity(activity_id, dl_fmt="gpx")
            if not gpx:
                return points
            if isinstance(gpx, bytes):
                gpx_text = gpx.decode("utf-8", errors="ignore")
            else:
                gpx_text = str(gpx)

            root = ET.fromstring(gpx_text)
            namespaces = {"gpx": "http://www.topografix.com/GPX/1/1"}
            for node in root.findall(".//gpx:trkpt", namespaces):
                lat = node.attrib.get("lat")
                lon = node.attrib.get("lon")
                if lat and lon:
                    points.append([float(lat), float(lon)])
        except Exception:
            return []
        return points

    def get_track_points(self, activity_id):
        if self.api is None:
            self.login()

        details = self.api.get_activity_details(activity_id)
        points = self._extract_track_from_metrics(details)
        if points:
            return points

        points = self._extract_track_from_polyline_list(details)
        if points:
            return points

        return self._extract_track_from_gpx(activity_id)

    def import_activities(self):
        all_activities = self.get_activities()
        start_date = datetime.strptime(self.start_date, "%Y-%m-%d")
        filtered = []
        for activity in all_activities:
            start_value = activity.get("startTimeLocal")
            if not start_value:
                continue
            dt = self._parse_local_time(start_value)
            if dt >= start_date and self._activity_is_cycling(activity):
                filtered.append(activity)
        filtered.sort(key=lambda row: row.get("startTimeLocal", ""))
        return filtered
