"""
Integration tests for Strava OAuth, token management, and webhook endpoints.

All external HTTP calls are mocked – no real Strava API is accessed.
"""

import json
import os
import sys
import time
from unittest.mock import MagicMock, patch, PropertyMock

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

def _insert_tokens(conn, athlete_id="123", expires_at=None):
    if expires_at is None:
        expires_at = int(time.time()) + 3600
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO strava_tokens
               (athlete_id, access_token, refresh_token, expires_at, scope, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
        (athlete_id, "acc_tok", "ref_tok", expires_at, "activity:read_all"),
    )
    conn.commit()


def _get_conn():
    from bikepacking.database import get_connection
    return get_connection()


# ---------------------------------------------------------------------------
# Tests: token storage and refresh
# ---------------------------------------------------------------------------

class TestTokenManagement:
    def test_save_and_load_tokens(self, tmp_db):
        import bikepacking.strava_client as sc
        sc._save_tokens("ath1", "acc", "ref", 9999999, "activity:read_all")
        tokens = sc._load_tokens()
        assert tokens["athlete_id"] == "ath1"
        assert tokens["access_token"] == "acc"
        assert tokens["refresh_token"] == "ref"
        assert tokens["expires_at"] == 9999999

    def test_update_existing_tokens(self, tmp_db):
        import bikepacking.strava_client as sc
        sc._save_tokens("ath1", "acc1", "ref1", 1000, "")
        sc._save_tokens("ath1", "acc2", "ref2", 2000, "")
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt FROM strava_tokens")
        count = cursor.fetchone()["cnt"]
        conn.close()
        assert count == 1  # must not create duplicate row

        tokens = sc._load_tokens()
        assert tokens["access_token"] == "acc2"

    def test_delete_tokens(self, tmp_db):
        import bikepacking.strava_client as sc
        sc._save_tokens("ath1", "acc", "ref", 9999, "")
        sc.delete_tokens()
        assert sc._load_tokens() is None
        assert sc.is_connected() is False

    def test_token_refresh_when_expired(self, tmp_db):
        import bikepacking.strava_client as sc
        # Store expired token
        expired_ts = int(time.time()) - 10
        sc._save_tokens("ath1", "old_acc", "ref_tok", expired_ts, "activity:read_all")

        new_ts = int(time.time()) + 3600
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_acc",
            "refresh_token": "new_ref",
            "expires_at": new_ts,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("bikepacking.strava_client.requests.post", return_value=mock_response) as mock_post:
            tokens = sc._load_tokens()
            refreshed = sc._refresh_tokens_if_needed(tokens)

        assert refreshed["access_token"] == "new_acc"
        # Verify token_url was called with refresh_token grant
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["data"]["grant_type"] == "refresh_token"
        assert call_kwargs[1]["data"]["refresh_token"] == "ref_tok"

    def test_no_refresh_when_not_expired(self, tmp_db):
        import bikepacking.strava_client as sc
        future_ts = int(time.time()) + 7200
        sc._save_tokens("ath1", "valid_acc", "ref", future_ts, "")
        tokens = sc._load_tokens()
        with patch("bikepacking.strava_client.requests.post") as mock_post:
            refreshed = sc._refresh_tokens_if_needed(tokens)
        mock_post.assert_not_called()
        assert refreshed["access_token"] == "valid_acc"

    def test_is_connected_false_without_tokens(self, tmp_db):
        import bikepacking.strava_client as sc
        assert sc.is_connected() is False

    def test_is_connected_true_with_tokens(self, tmp_db):
        import bikepacking.strava_client as sc
        sc._save_tokens("ath1", "acc", "ref", 9999999, "")
        assert sc.is_connected() is True


# ---------------------------------------------------------------------------
# Tests: OAuth exchange
# ---------------------------------------------------------------------------

class TestOAuthExchange:
    def test_exchange_code_for_tokens(self, tmp_db):
        import bikepacking.strava_client as sc
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_acc",
            "refresh_token": "new_ref",
            "expires_at": int(time.time()) + 3600,
            "athlete": {"id": 9876},
            "scope": "activity:read_all",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("bikepacking.strava_client.requests.post", return_value=mock_response):
            athlete_id = sc.exchange_code_for_tokens("auth_code_123")

        assert athlete_id == "9876"
        tokens = sc._load_tokens()
        assert tokens["access_token"] == "new_acc"
        assert tokens["athlete_id"] == "9876"


# ---------------------------------------------------------------------------
# Tests: webhook endpoint (Flask integration)
# ---------------------------------------------------------------------------

class TestWebhookEndpoint:
    def test_webhook_challenge_verification(self, app_client):
        """GET /strava/webhook must respond with hub.challenge when token matches."""
        resp = app_client.get(
            "/strava/webhook",
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": "test_verify_token",
                "hub.challenge": "abc123",
            },
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["hub.challenge"] == "abc123"

    def test_webhook_challenge_wrong_token(self, app_client):
        """GET /strava/webhook must return 403 when token does not match."""
        resp = app_client.get(
            "/strava/webhook",
            query_string={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "abc123",
            },
        )
        assert resp.status_code == 403

    def test_webhook_post_returns_200_immediately(self, app_client):
        """POST /strava/webhook must return 200 regardless of event content."""
        payload = {
            "object_type": "activity",
            "aspect_type": "create",
            "object_id": 12345,
            "owner_id": 67890,
        }
        with patch("bikepacking.strava_import.handle_webhook_create"):
            resp = app_client.post(
                "/strava/webhook",
                data=json.dumps(payload),
                content_type="application/json",
            )
        assert resp.status_code == 200

    def test_webhook_post_empty_body_returns_200(self, app_client):
        """Malformed / empty webhook payloads must not crash the endpoint."""
        resp = app_client.post(
            "/strava/webhook",
            data="not-json",
            content_type="text/plain",
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: webhook event processing
# ---------------------------------------------------------------------------

class TestWebhookEventProcessing:
    def test_create_event_triggers_import(self, tmp_db, monkeypatch):
        """handle_webhook_create should fetch and upsert a bikepacking activity."""
        import bikepacking.strava_client as sc_mod
        import bikepacking.strava_import as si_mod

        # Setup tour
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tours (name, start_date, end_date, description) "
            "VALUES ('T','2026-07-01','2026-07-05','')"
        )
        conn.commit()
        conn.close()

        # Store valid tokens so is_connected() is True
        sc_mod._save_tokens("123", "acc", "ref", int(time.time()) + 3600, "")

        activity = {
            "id": 555,
            "sport_type": "Ride",
            "type": "Ride",
            "start_date_local": "2026-07-02T09:00:00Z",
            "name": "Webhook Ride",
            "distance": 50_000,
            "moving_time": 5400,
            "elapsed_time": 6000,
            "total_elevation_gain": 400,
            "average_speed": 9.26,
            "max_speed": 15.0,
        }

        monkeypatch.setattr(sc_mod, "get_activity_detail", lambda _id: activity)
        monkeypatch.setattr(sc_mod, "get_activity_streams", lambda _id: {})
        monkeypatch.setattr(si_mod, "rebuild_rest_days", lambda _tid: None)

        si_mod.handle_webhook_create(555, 123)

        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stages WHERE external_activity_id='555'")
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        assert row["title"] == "Webhook Ride"
        assert row["source"] == "strava"

    def test_delete_event_removes_stage(self, tmp_db, monkeypatch):
        """handle_webhook_delete should remove the stage and recreate a rest day."""
        import bikepacking.strava_import as si_mod

        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tours (name, start_date, end_date) VALUES ('T','2026-07-01','2026-07-01')"
        )
        tour_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO stages (tour_id, date, title, is_rest_day, source, "
            "external_activity_id, diary_text, rating) "
            "VALUES (?, '2026-07-01', 'Ride', 0, 'strava', '999', '', '')",
            (tour_id,),
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(si_mod, "_ensure_rest_day_for", MagicMock())

        si_mod.handle_webhook_delete(999, 123)

        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt FROM stages WHERE external_activity_id='999'")
        count = cursor.fetchone()["cnt"]
        conn.close()
        assert count == 0
        si_mod._ensure_rest_day_for.assert_called_once_with(tour_id, "2026-07-01")

    def test_deauthorize_event_removes_tokens(self, tmp_db):
        """handle_webhook_deauthorize should delete all stored tokens."""
        import bikepacking.strava_client as sc_mod
        import bikepacking.strava_import as si_mod
        sc_mod._save_tokens("123", "acc", "ref", 9999999, "")
        si_mod.handle_webhook_deauthorize("123")
        assert sc_mod._load_tokens() is None

    def test_update_event_updates_stage(self, tmp_db, monkeypatch):
        """handle_webhook_update should re-fetch and update an existing stage."""
        import bikepacking.strava_client as sc_mod
        import bikepacking.strava_import as si_mod

        sc_mod._save_tokens("123", "acc", "ref", int(time.time()) + 3600, "")

        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tours (name, start_date, end_date) VALUES ('T','2026-07-01','2026-07-05')"
        )
        tour_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO stages (tour_id, date, title, is_rest_day, source, "
            "external_activity_id, diary_text, rating) "
            "VALUES (?, '2026-07-01', 'Old Title', 0, 'strava', '777', '', '')",
            (tour_id,),
        )
        conn.commit()
        conn.close()

        updated_activity = {
            "id": 777,
            "sport_type": "Ride",
            "type": "Ride",
            "start_date_local": "2026-07-01T09:00:00Z",
            "name": "Updated Title",
            "distance": 60_000,
            "moving_time": 7200,
            "elapsed_time": 8000,
            "total_elevation_gain": 600,
            "average_speed": 8.33,
            "max_speed": 14.0,
        }
        monkeypatch.setattr(sc_mod, "get_activity_detail", lambda _id: updated_activity)
        monkeypatch.setattr(sc_mod, "get_activity_streams", lambda _id: {})
        monkeypatch.setattr(si_mod, "rebuild_rest_days", lambda _tid: None)

        si_mod.handle_webhook_update(777, 123, {"title": "Updated Title"})

        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM stages WHERE external_activity_id='777'")
        row = cursor.fetchone()
        conn.close()
        assert row["title"] == "Updated Title"


# ---------------------------------------------------------------------------
# Tests: OAuth Flask routes
# ---------------------------------------------------------------------------

class TestOAuthRoutes:
    def test_connect_redirect_when_configured(self, app_client):
        """GET /strava/connect should redirect to Strava auth URL."""
        resp = app_client.get("/strava/connect")
        assert resp.status_code == 302
        assert "strava.com" in resp.headers.get("Location", "")

    def test_callback_with_error_redirects_to_settings(self, app_client):
        """Strava auth errors must redirect to settings with an error flash."""
        resp = app_client.get("/strava/callback?error=access_denied")
        assert resp.status_code == 302
        assert "settings" in resp.headers.get("Location", "")

    def test_callback_no_code_redirects_to_settings(self, app_client):
        resp = app_client.get("/strava/callback")
        assert resp.status_code == 302

    def test_callback_exchanges_code_and_redirects(self, app_client, tmp_db):
        import time
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "acc",
            "refresh_token": "ref",
            "expires_at": int(time.time()) + 3600,
            "athlete": {"id": 42},
            "scope": "activity:read_all",
        }
        mock_response.raise_for_status = MagicMock()
        with patch("bikepacking.strava_client.requests.post", return_value=mock_response):
            resp = app_client.get("/strava/callback?code=mycode")
        assert resp.status_code == 302

    def test_disconnect_removes_tokens(self, app_client, tmp_db):
        import bikepacking.strava_client as sc_mod
        sc_mod._save_tokens("ath", "acc", "ref", 9999999, "")
        resp = app_client.post("/strava/disconnect")
        assert resp.status_code == 302
        assert sc_mod._load_tokens() is None
