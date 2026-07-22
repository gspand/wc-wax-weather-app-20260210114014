"""
Shared pytest fixtures for Strava integration tests.
"""

import os
import sys
import tempfile
import pytest

# Ensure the project root is on sys.path so imports work without installation
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Set required env vars before any app-level imports
os.environ.setdefault("STRAVA_CLIENT_ID", "test_client_id")
os.environ.setdefault("STRAVA_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("STRAVA_CALLBACK_URL", "http://localhost/strava/callback")
os.environ.setdefault("STRAVA_WEBHOOK_VERIFY_TOKEN", "test_verify_token")
os.environ.setdefault("DEMO_MODE", "0")


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """
    Provide a fresh temporary SQLite database for each test.
    Patches Config.DATABASE_PATH so every DB call goes to the temp file.
    """
    db_file = str(tmp_path / "test_bikepacking.db")
    # Patch at the Config class level and also in the database module
    from config import Config
    monkeypatch.setattr(Config, "DATABASE_PATH", db_file)
    monkeypatch.setattr(Config, "DATA_DIR", str(tmp_path))

    # Re-import database module so it picks up the patched path
    import importlib
    import bikepacking.database as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()

    yield db_file

    # Cleanup is handled by tmp_path fixture


@pytest.fixture()
def app_client(tmp_db, monkeypatch):
    """
    Flask test client with a fresh database.
    """
    from config import Config
    monkeypatch.setattr(Config, "DEMO_MODE", False)

    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.app.config["SECRET_KEY"] = "testing"
    with app_module.app.test_client() as client:
        with app_module.app.app_context():
            yield client
