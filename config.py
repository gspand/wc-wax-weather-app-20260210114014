import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-locally")
    DATA_DIR = os.path.join(BASE_DIR, "data")
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
    DATABASE_PATH = os.path.join(DATA_DIR, "bikepacking.db")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"
    GARMIN_USERNAME = os.environ.get("GARMIN_USERNAME", "")
    GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "")
    GARMIN_START_DATE = os.environ.get("GARMIN_START_DATE", "2026-06-27")
    GARMIN_CACHE_DIR = os.path.join(DATA_DIR, "tracks")
    MAP_PROVIDER = os.environ.get("MAP_PROVIDER", "google")
    GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    MAP_LANGUAGE = os.environ.get("MAP_LANGUAGE", "de-DE")
    MAP_REGION = os.environ.get("MAP_REGION", "AT")
    # Strava OAuth – read exclusively from environment variables
    STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID", "")
    STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET", "")
    STRAVA_CALLBACK_URL = os.environ.get("STRAVA_CALLBACK_URL", "")
    STRAVA_WEBHOOK_VERIFY_TOKEN = os.environ.get("STRAVA_WEBHOOK_VERIFY_TOKEN", "")
