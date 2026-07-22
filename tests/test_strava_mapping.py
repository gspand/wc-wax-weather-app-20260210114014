"""
Unit tests for Strava activity mapping and rest-day management.

Tests cover:
- Activity-to-stage field mapping
- Sport-type filtering (bikepacking vs. VirtualRide)
- Multiple activities on the same day
- Rest-day creation and promotion/demotion
- Timezone / midnight-boundary handling
- Idempotent upsert (no duplicates on repeated import)
"""

import json
import os
import sys
import sqlite3
from datetime import date, datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("STRAVA_CLIENT_ID", "test_client_id")
os.environ.setdefault("STRAVA_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("STRAVA_CALLBACK_URL", "http://localhost/strava/callback")
os.environ.setdefault("STRAVA_WEBHOOK_VERIFY_TOKEN", "test_verify_token")
os.environ.setdefault("DEMO_MODE", "0")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_activity(
    activity_id=42,
    sport_type="Ride",
    start_date_local="2026-07-01T08:00:00Z",
    distance=100_000,
    moving_time=3600,
    elapsed_time=4000,
    elevation=500,
    avg_speed=10.0,
    max_speed=15.0,
    avg_hr=140.0,
    max_hr=175.0,
    avg_cadence=85.0,
    name="Morning Ride",
):
    return {
        "id": activity_id,
        "sport_type": sport_type,
        "type": sport_type,
        "start_date_local": start_date_local,
        "name": name,
        "distance": distance,
        "moving_time": moving_time,
        "elapsed_time": elapsed_time,
        "total_elevation_gain": elevation,
        "average_speed": avg_speed,
        "max_speed": max_speed,
        "average_heartrate": avg_hr,
        "max_heartrate": max_hr,
        "average_cadence": avg_cadence,
    }


def _setup_tour(conn, start_date="2026-07-01", end_date="2026-07-05"):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tours (name, start_date, end_date, description) VALUES (?,?,?,?)",
        ("Test Tour", start_date, end_date, ""),
    )
    conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Tests: activity field mapping
# ---------------------------------------------------------------------------

class TestActivityMapping:
    def test_basic_field_mapping(self, tmp_db):
        from bikepacking.strava_import import _map_activity_to_stage
        activity = _make_activity(activity_id=1, distance=80_000, moving_time=7200)
        result = _map_activity_to_stage(activity, detail={}, streams={}, tour_id=1, color="#ff0000")

        assert result["external_activity_id"] == "1"
        assert result["source"] == "strava"
        assert result["distance"] == pytest.approx(80.0, abs=0.1)
        assert result["moving_time"] == 7200
        assert result["date"] == "2026-07-01"
        assert result["title"] == "Morning Ride"
        assert result["is_rest_day"] == 0

    def test_speed_conversion_ms_to_kmh(self, tmp_db):
        from bikepacking.strava_import import _map_activity_to_stage
        activity = _make_activity(avg_speed=10.0, max_speed=20.0)
        result = _map_activity_to_stage(activity, detail={}, streams={}, tour_id=1, color="#aaa")
        assert result["average_speed"] == pytest.approx(36.0, abs=0.1)
        assert result["max_speed"] == pytest.approx(72.0, abs=0.1)

    def test_elevation_rounded(self, tmp_db):
        from bikepacking.strava_import import _map_activity_to_stage
        activity = _make_activity(elevation=1234.7)
        result = _map_activity_to_stage(activity, detail={}, streams={}, tour_id=1, color="#aaa")
        assert result["elevation_gain"] == 1235

    def test_avg_power_from_detail(self, tmp_db):
        from bikepacking.strava_import import _map_activity_to_stage
        activity = _make_activity()
        detail = {"average_watts": 210.5}
        result = _map_activity_to_stage(activity, detail=detail, streams={}, tour_id=1, color="#aaa")
        assert result["average_power"] == 210.5

    def test_track_geojson_built_from_streams(self, tmp_db):
        from bikepacking.strava_import import _map_activity_to_stage
        streams = {
            "latlng": {"data": [[47.0, 15.0], [47.1, 15.1]]},
            "altitude": {"data": [500, 510]},
        }
        activity = _make_activity()
        result = _map_activity_to_stage(activity, detail={}, streams=streams, tour_id=1, color="#aaa")
        geo = json.loads(result["track_geojson"])
        coords = geo["features"][0]["geometry"]["coordinates"]
        assert coords[0] == [15.0, 47.0, 500]
        assert coords[1] == [15.1, 47.1, 510]

    def test_no_track_when_no_streams(self, tmp_db):
        from bikepacking.strava_import import _map_activity_to_stage
        activity = _make_activity()
        result = _map_activity_to_stage(activity, detail={}, streams={}, tour_id=1, color="#aaa")
        assert result["track_geojson"] is None


# ---------------------------------------------------------------------------
# Tests: sport-type filtering
# ---------------------------------------------------------------------------

class TestSportTypeFiltering:
    @pytest.mark.parametrize("sport", ["Ride", "GravelRide", "MountainBikeRide", "EBikeRide"])
    def test_bikepacking_types_accepted(self, sport):
        from bikepacking.strava_client import is_bikepacking_activity
        activity = {"sport_type": sport}
        assert is_bikepacking_activity(activity) is True

    @pytest.mark.parametrize("sport", ["VirtualRide", "Run", "Swim", "Walk", "Workout"])
    def test_non_bikepacking_types_rejected(self, sport):
        from bikepacking.strava_client import is_bikepacking_activity
        activity = {"sport_type": sport}
        assert is_bikepacking_activity(activity) is False

    def test_upsert_raises_for_virtual_ride(self, tmp_db):
        from bikepacking.strava_import import upsert_strava_stage
        activity = _make_activity(sport_type="VirtualRide")
        with pytest.raises(ValueError, match="not a bikepacking"):
            upsert_strava_stage(activity, tour_id=1)


# ---------------------------------------------------------------------------
# Tests: rest-day management
# ---------------------------------------------------------------------------

class TestRestDays:
    def _get_conn(self):
        from bikepacking.database import get_connection
        return get_connection()

    def test_rest_days_created_for_empty_days(self, tmp_db):
        from bikepacking.strava_import import rebuild_rest_days
        conn = self._get_conn()
        tour_id = _setup_tour(conn, "2026-07-01", "2026-07-03")
        conn.close()

        rebuild_rest_days(tour_id)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT date FROM stages WHERE tour_id=? AND is_rest_day=1 ORDER BY date",
            (tour_id,),
        )
        rest_days = [row["date"] for row in cursor.fetchall()]
        conn.close()

        assert rest_days == ["2026-07-01", "2026-07-02", "2026-07-03"]

    def test_no_rest_day_when_activity_exists(self, tmp_db):
        from bikepacking.strava_import import rebuild_rest_days
        from bikepacking.database import get_connection
        conn = self._get_conn()
        tour_id = _setup_tour(conn, "2026-07-01", "2026-07-02")
        # Insert an active stage on 2026-07-01
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO stages (tour_id, date, title, is_rest_day, source, diary_text, rating) "
            "VALUES (?, '2026-07-01', 'Active', 0, 'strava', '', '')",
            (tour_id,),
        )
        conn.commit()
        conn.close()

        rebuild_rest_days(tour_id)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT date, is_rest_day FROM stages WHERE tour_id=? ORDER BY date",
            (tour_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        dates = {r["date"]: r["is_rest_day"] for r in rows}
        assert dates["2026-07-01"] == 0  # activity day, not rest
        assert dates["2026-07-02"] == 1  # no activity → rest

    def test_rest_day_removed_when_activity_added(self, tmp_db):
        from bikepacking.strava_import import rebuild_rest_days, _ensure_rest_day_for
        conn = self._get_conn()
        tour_id = _setup_tour(conn, "2026-07-01", "2026-07-01")
        conn.close()

        # First: no activity → rest day created
        rebuild_rest_days(tour_id)
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM stages WHERE tour_id=? AND is_rest_day=1",
            (tour_id,),
        )
        assert cursor.fetchone()["cnt"] == 1
        conn.close()

        # Now add an activity
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO stages (tour_id, date, title, is_rest_day, source, diary_text, rating) "
            "VALUES (?, '2026-07-01', 'Ride', 0, 'strava', '', '')",
            (tour_id,),
        )
        conn.commit()
        conn.close()

        _ensure_rest_day_for(tour_id, "2026-07-01")

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM stages WHERE tour_id=? AND is_rest_day=1",
            (tour_id,),
        )
        assert cursor.fetchone()["cnt"] == 0
        conn.close()

    def test_rest_day_reinstated_after_activity_deleted(self, tmp_db):
        from bikepacking.strava_import import _ensure_rest_day_for
        conn = self._get_conn()
        tour_id = _setup_tour(conn, "2026-07-01", "2026-07-01")
        # Active stage
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO stages (tour_id, date, title, is_rest_day, source, diary_text, rating) "
            "VALUES (?, '2026-07-01', 'Ride', 0, 'strava', '', '')",
            (tour_id,),
        )
        stage_id = cursor.lastrowid
        conn.commit()

        # Delete the activity (simulating webhook delete)
        cursor.execute("DELETE FROM stages WHERE id=?", (stage_id,))
        conn.commit()
        conn.close()

        _ensure_rest_day_for(tour_id, "2026-07-01")

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM stages WHERE tour_id=? AND is_rest_day=1",
            (tour_id,),
        )
        assert cursor.fetchone()["cnt"] == 1
        conn.close()

    def test_no_rest_days_outside_tour_range(self, tmp_db):
        from bikepacking.strava_import import rebuild_rest_days
        conn = self._get_conn()
        tour_id = _setup_tour(conn, "2026-07-02", "2026-07-02")
        conn.close()

        rebuild_rest_days(tour_id)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT date FROM stages WHERE tour_id=? AND is_rest_day=1",
            (tour_id,),
        )
        rest_days = [row["date"] for row in cursor.fetchall()]
        conn.close()
        # Only the one day within the range should have a rest day
        assert rest_days == ["2026-07-02"]
        assert "2026-07-01" not in rest_days
        assert "2026-07-03" not in rest_days

    def test_rest_days_support_photos_diary_weather_fields(self, tmp_db):
        """Rest-day stages store diary, rating and location like normal stages."""
        from bikepacking.strava_import import rebuild_rest_days
        from bikepacking.database import get_connection
        conn = self._get_conn()
        tour_id = _setup_tour(conn, "2026-07-01", "2026-07-01")
        conn.close()
        rebuild_rest_days(tour_id)

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM stages WHERE tour_id=? AND is_rest_day=1", (tour_id,)
        )
        rest_id = cursor.fetchone()["id"]
        # Write diary text and location
        cursor.execute(
            "UPDATE stages SET diary_text=?, location=? WHERE id=?",
            ("Rest day text", "Innsbruck", rest_id),
        )
        conn.commit()
        cursor.execute(
            "SELECT diary_text, location FROM stages WHERE id=?", (rest_id,)
        )
        row = cursor.fetchone()
        conn.close()
        assert row["diary_text"] == "Rest day text"
        assert row["location"] == "Innsbruck"


# ---------------------------------------------------------------------------
# Tests: multiple activities per day
# ---------------------------------------------------------------------------

class TestMultipleActivitiesPerDay:
    def _get_conn(self):
        from bikepacking.database import get_connection
        return get_connection()

    def test_two_activities_same_day_no_rest_day(self, tmp_db):
        from bikepacking.strava_import import rebuild_rest_days
        conn = self._get_conn()
        tour_id = _setup_tour(conn, "2026-07-01", "2026-07-01")
        cursor = conn.cursor()
        for i in range(2):
            cursor.execute(
                "INSERT INTO stages (tour_id, date, title, is_rest_day, source, "
                "external_activity_id, diary_text, rating) "
                "VALUES (?, '2026-07-01', ?, 0, 'strava', ?, '', '')",
                (tour_id, f"Ride {i}", str(100 + i)),
            )
        conn.commit()
        conn.close()

        rebuild_rest_days(tour_id)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM stages WHERE tour_id=? AND is_rest_day=1",
            (tour_id,),
        )
        assert cursor.fetchone()["cnt"] == 0
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM stages WHERE tour_id=? AND is_rest_day=0",
            (tour_id,),
        )
        assert cursor.fetchone()["cnt"] == 2
        conn.close()


# ---------------------------------------------------------------------------
# Tests: idempotent upsert
# ---------------------------------------------------------------------------

class TestIdempotentUpsert:
    def _get_conn(self):
        from bikepacking.database import get_connection
        return get_connection()

    def test_duplicate_import_does_not_create_two_stages(self, tmp_db, monkeypatch):
        """Calling upsert twice for the same activity_id must not create two rows."""
        import bikepacking.strava_client as sc_mod
        # Mock out the API calls
        monkeypatch.setattr(sc_mod, "get_activity_detail", lambda _id: {})
        monkeypatch.setattr(sc_mod, "get_activity_streams", lambda _id: {})

        from bikepacking.strava_import import upsert_strava_stage
        conn = self._get_conn()
        tour_id = _setup_tour(conn, "2026-07-01", "2026-07-01")
        conn.close()

        activity = _make_activity(activity_id=99)
        action1, sid1 = upsert_strava_stage(activity, tour_id, color_index=0)
        action2, sid2 = upsert_strava_stage(activity, tour_id, color_index=0)

        assert action1 == "inserted"
        assert action2 == "updated"
        assert sid1 == sid2  # same stage record

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM stages WHERE external_activity_id='99' AND source='strava'",
        )
        assert cursor.fetchone()["cnt"] == 1
        conn.close()


# ---------------------------------------------------------------------------
# Tests: timezone / midnight boundary
# ---------------------------------------------------------------------------

class TestTimezoneHandling:
    def test_local_date_extracted_correctly(self):
        from bikepacking.strava_import import _local_date_from_activity
        # UTC midnight but local date is day before
        activity = {"start_date_local": "2026-07-01T23:55:00Z", "start_date": "2026-07-02T00:55:00Z"}
        # start_date_local is preferred
        assert _local_date_from_activity(activity) == "2026-07-01"

    def test_local_date_falls_back_to_utc(self):
        from bikepacking.strava_import import _local_date_from_activity
        activity = {"start_date": "2026-07-02T00:55:00Z"}
        assert _local_date_from_activity(activity) == "2026-07-02"

    def test_activity_at_midnight_utc_correct_day(self, tmp_db, monkeypatch):
        """Activity starting at 23:50 local should be filed under local date."""
        import bikepacking.strava_client as sc_mod
        monkeypatch.setattr(sc_mod, "get_activity_detail", lambda _id: {})
        monkeypatch.setattr(sc_mod, "get_activity_streams", lambda _id: {})

        from bikepacking.strava_import import upsert_strava_stage
        from bikepacking.database import get_connection
        conn = get_connection()
        tour_id = _setup_tour(conn, "2026-07-01", "2026-07-02")
        conn.close()

        # Local start at 23:50 on 2026-07-01, UTC would be next day
        activity = _make_activity(activity_id=77, start_date_local="2026-07-01T23:50:00Z")
        upsert_strava_stage(activity, tour_id, color_index=0)

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT date FROM stages WHERE external_activity_id='77'")
        row = cursor.fetchone()
        conn.close()
        assert row["date"] == "2026-07-01"


# ---------------------------------------------------------------------------
# Tests: strava_client helpers
# ---------------------------------------------------------------------------

class TestStravaClientHelpers:
    def test_build_track_geojson_no_altitude(self):
        from bikepacking.strava_client import build_track_geojson
        streams = {"latlng": {"data": [[47.0, 15.0], [47.1, 15.1]]}}
        geo = build_track_geojson(streams)
        assert geo is not None
        coords = geo["features"][0]["geometry"]["coordinates"]
        assert len(coords) == 2
        assert coords[0] == [15.0, 47.0]  # [lon, lat]

    def test_build_track_geojson_returns_none_without_data(self):
        from bikepacking.strava_client import build_track_geojson
        assert build_track_geojson({}) is None
        assert build_track_geojson({"latlng": {"data": []}}) is None

    def test_build_track_geojson_with_altitude(self):
        from bikepacking.strava_client import build_track_geojson
        streams = {
            "latlng": {"data": [[47.0, 15.0]]},
            "altitude": {"data": [550.5]},
        }
        geo = build_track_geojson(streams)
        coords = geo["features"][0]["geometry"]["coordinates"]
        assert coords[0] == [15.0, 47.0, 550.5]

    def test_get_authorization_url_contains_client_id(self):
        from bikepacking.strava_client import get_authorization_url
        from urllib.parse import unquote
        url = get_authorization_url()
        decoded = unquote(url)
        assert "test_client_id" in decoded
        assert "activity:read_all" in decoded

    def test_is_configured_true_when_vars_set(self):
        from bikepacking.strava_client import is_configured
        assert is_configured() is True

    def test_is_configured_false_when_vars_missing(self, monkeypatch):
        from config import Config
        monkeypatch.setattr(Config, "STRAVA_CLIENT_ID", "")
        import importlib
        import bikepacking.strava_client as sc_mod
        importlib.reload(sc_mod)
        assert sc_mod.is_configured() is False
