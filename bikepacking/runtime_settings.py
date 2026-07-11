import json
from pathlib import Path

from config import Config


RUNTIME_SETTINGS_FILE = Path(Config.DATA_DIR) / "runtime_settings.json"


DEFAULT_SETTINGS = {
    "GARMIN_USERNAME": "",
    "GARMIN_PASSWORD": "",
    "GARMIN_START_DATE": Config.GARMIN_START_DATE,
    "GARMIN_LAST_IMPORT_STATUS": "",
    "GARMIN_LAST_IMPORT_AT": "",
    "GARMIN_LAST_ERROR": "",
    "GARMIN_NEXT_RETRY_AT": "",
    "MAP_PROVIDER": Config.MAP_PROVIDER,
    "GOOGLE_MAPS_API_KEY": Config.GOOGLE_MAPS_API_KEY,
    "MAP_LANGUAGE": Config.MAP_LANGUAGE,
    "MAP_REGION": Config.MAP_REGION,
}


def load_runtime_settings():
    if not RUNTIME_SETTINGS_FILE.exists():
        return dict(DEFAULT_SETTINGS)

    try:
        data = json.loads(RUNTIME_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_SETTINGS)

    merged = dict(DEFAULT_SETTINGS)
    merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    return merged


def save_runtime_settings(updates):
    current = load_runtime_settings()
    for key, value in updates.items():
        if key in current and value is not None:
            current[key] = value

    RUNTIME_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_SETTINGS_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current