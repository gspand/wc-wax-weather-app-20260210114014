import json
import os
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename

from config import Config
from bikepacking.database import init_db
from bikepacking.services import (
    create_demo_data,
    get_tour,
    get_tour_summary,
    get_stages,
    get_stage,
    get_stage_photos,
    save_stage_diary,
    save_stage_rating,
    save_stage_photo,
    get_stage_geojson,
    get_all_stages_geojson,
    import_from_garmin,
    import_from_colab_json,
)
from bikepacking.garmin_client import GarminClient
from bikepacking.runtime_settings import load_runtime_settings, save_runtime_settings

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = app.config.get("SECRET_KEY", "change-me-locally")

GARMIN_IMPORT_COOLDOWN_MINUTES = 45

init_db()
create_demo_data()

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


def get_tile_layer_config():
    runtime = load_runtime_settings()
    provider = (runtime.get("MAP_PROVIDER") or app.config.get("MAP_PROVIDER", "google")).lower()
    api_key = runtime.get("GOOGLE_MAPS_API_KEY") or app.config.get("GOOGLE_MAPS_API_KEY", "")
    map_language = runtime.get("MAP_LANGUAGE") or app.config.get("MAP_LANGUAGE", "de-DE")
    map_region = runtime.get("MAP_REGION") or app.config.get("MAP_REGION", "AT")

    if provider == "google" and api_key:
        return {
            "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            "attribution": "&copy; OpenStreetMap contributors",
            "max_zoom": 19,
            "provider": "google-terrain",
            "status": "Google Terrain wird geladen",
            "mode": "google-client",
            "google_api_key": api_key,
            "map_language": map_language,
            "map_region": map_region,
            "google_max_zoom": 20,
        }

    if provider == "google" and not api_key:
        return {
            "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            "attribution": "&copy; OpenStreetMap contributors",
            "max_zoom": 19,
            "provider": "osm",
            "status": "Google Terrain nicht aktiv: API Key fehlt",
            "mode": "osm",
        }

    return {
        "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": "&copy; OpenStreetMap contributors",
        "max_zoom": 19,
        "provider": "osm",
        "status": "OpenStreetMap aktiv",
        "mode": "osm",
    }


def _utcnow():
    return datetime.now(timezone.utc)


def _iso_now():
    return _utcnow().isoformat()


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def get_garmin_import_status(runtime):
    last_status = runtime.get("GARMIN_LAST_IMPORT_STATUS", "")
    last_error = runtime.get("GARMIN_LAST_ERROR", "")
    last_import_at = runtime.get("GARMIN_LAST_IMPORT_AT", "")
    next_retry_at = runtime.get("GARMIN_NEXT_RETRY_AT", "")
    next_retry_dt = _parse_iso(next_retry_at)

    cooldown_active = False
    retry_in_minutes = 0
    if next_retry_dt:
        now = _utcnow()
        if next_retry_dt > now:
            cooldown_active = True
            retry_in_minutes = int((next_retry_dt - now).total_seconds() // 60) + 1

    return {
        "last_status": last_status,
        "last_error": last_error,
        "last_import_at": last_import_at,
        "next_retry_at": next_retry_at,
        "cooldown_active": cooldown_active,
        "retry_in_minutes": retry_in_minutes,
    }


def try_startup_garmin_import_once():
    runtime = load_runtime_settings()
    status = get_garmin_import_status(runtime)

    if status["cooldown_active"]:
        return

    garmin = GarminClient()
    if not garmin.is_configured():
        return

    try:
        import_from_garmin()
        save_runtime_settings(
            {
                "GARMIN_LAST_IMPORT_STATUS": "success",
                "GARMIN_LAST_IMPORT_AT": _iso_now(),
                "GARMIN_LAST_ERROR": "",
                "GARMIN_NEXT_RETRY_AT": "",
            }
        )
    except Exception as exc:
        msg = str(exc)
        if "429" in msg:
            retry_at = (_utcnow() + timedelta(minutes=GARMIN_IMPORT_COOLDOWN_MINUTES)).isoformat()
            save_runtime_settings(
                {
                    "GARMIN_LAST_IMPORT_STATUS": "rate_limited",
                    "GARMIN_LAST_IMPORT_AT": _iso_now(),
                    "GARMIN_LAST_ERROR": msg,
                    "GARMIN_NEXT_RETRY_AT": retry_at,
                }
            )
        else:
            save_runtime_settings(
                {
                    "GARMIN_LAST_IMPORT_STATUS": "error",
                    "GARMIN_LAST_IMPORT_AT": _iso_now(),
                    "GARMIN_LAST_ERROR": msg,
                    "GARMIN_NEXT_RETRY_AT": "",
                }
            )


try_startup_garmin_import_once()

@app.route("/")
def index():
    tour = get_tour()
    stages = get_stages()
    summary = get_tour_summary()
    all_tracks_geojson = get_all_stages_geojson(stages)
    tile_layer = get_tile_layer_config()
    runtime = load_runtime_settings()
    garmin_import_status = get_garmin_import_status(runtime)
    return render_template(
        "index.html",
        tour=tour,
        stages=stages,
        summary=summary,
        all_tracks_geojson=json.dumps(all_tracks_geojson),
        tile_layer=tile_layer,
        garmin_import_status=garmin_import_status,
    )

@app.route("/stage/<int:stage_id>", methods=["GET", "POST"])
def stage_detail(stage_id):
    stage = get_stage(stage_id)
    if not stage:
        flash("Etappe nicht gefunden.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        diary_text = request.form.get("diary_text", "").strip()
        rating = request.form.get("rating")
        save_stage_diary(stage_id, diary_text)
        save_stage_rating(stage_id, rating)
        flash("Tagebuch gespeichert.", "success")
        return redirect(url_for("stage_detail", stage_id=stage_id))

    photos = get_stage_photos(stage_id)
    track_geojson = get_stage_geojson(stage)
    tile_layer = get_tile_layer_config()
    return render_template(
        "stage.html",
        stage=stage,
        photos=photos,
        track_geojson=json.dumps(track_geojson),
        tile_layer=tile_layer,
    )

@app.route("/stage/<int:stage_id>/photo", methods=["POST"])
def upload_photo(stage_id):
    stage = get_stage(stage_id)
    if not stage:
        flash("Etappe nicht gefunden.", "error")
        return redirect(url_for("index"))

    file = request.files.get("photo")
    caption = request.form.get("caption", "").strip()
    if not file or file.filename == "":
        flash("Kein Bild ausgewählt.", "error")
        return redirect(url_for("stage_detail", stage_id=stage_id))

    if not allowed_file(file.filename):
        flash("Nur Bilder im Format JPG, PNG oder WEBP sind erlaubt.", "error")
        return redirect(url_for("stage_detail", stage_id=stage_id))

    filename = secure_filename(file.filename)
    saved = save_stage_photo(stage_id, file, filename, caption)
    if saved:
        flash("Bild gespeichert.", "success")
    else:
        flash("Bild konnte nicht gespeichert werden.", "error")
    return redirect(url_for("stage_detail", stage_id=stage_id))

@app.route("/settings", methods=["GET"])
def settings():
    runtime = load_runtime_settings()
    garmin = GarminClient()
    garmin_import_status = get_garmin_import_status(runtime)
    return render_template(
        "settings.html",
        garmin_username=garmin.username,
        garmin_start_date=garmin.start_date,
        garmin_password_set=bool(garmin.password),
        garmin_token_cached=garmin.token_store_path.exists(),
        map_provider=runtime.get("MAP_PROVIDER", app.config.get("MAP_PROVIDER", "google")),
        google_maps_api_key=runtime.get("GOOGLE_MAPS_API_KEY", ""),
        map_language=runtime.get("MAP_LANGUAGE", app.config.get("MAP_LANGUAGE", "de-DE")),
        map_region=runtime.get("MAP_REGION", app.config.get("MAP_REGION", "AT")),
        demo_mode=app.config["DEMO_MODE"],
        garmin_import_status=garmin_import_status,
    )


@app.route("/settings/garmin", methods=["POST"])
def save_garmin_settings():
    current = load_runtime_settings()
    username = request.form.get("garmin_username", "").strip()
    password = request.form.get("garmin_password", "").strip()
    start_date = request.form.get("garmin_start_date", "").strip()
    map_provider = request.form.get("map_provider", "").strip() or current.get("MAP_PROVIDER", "google")
    google_maps_api_key = request.form.get("google_maps_api_key", "").strip() or current.get("GOOGLE_MAPS_API_KEY", "")
    map_language = request.form.get("map_language", "").strip() or current.get("MAP_LANGUAGE", "de-DE")
    map_region = request.form.get("map_region", "").strip() or current.get("MAP_REGION", "AT")

    if username:
        os.environ["GARMIN_USERNAME"] = username
        app.config["GARMIN_USERNAME"] = username
    else:
        username = current.get("GARMIN_USERNAME", "")
    if password:
        os.environ["GARMIN_PASSWORD"] = password
        app.config["GARMIN_PASSWORD"] = password
    else:
        password = current.get("GARMIN_PASSWORD", "")
    if start_date:
        os.environ["GARMIN_START_DATE"] = start_date
        app.config["GARMIN_START_DATE"] = start_date
    else:
        start_date = current.get("GARMIN_START_DATE", app.config.get("GARMIN_START_DATE", "2026-06-27"))

    if google_maps_api_key:
        os.environ["GOOGLE_MAPS_API_KEY"] = google_maps_api_key
        app.config["GOOGLE_MAPS_API_KEY"] = google_maps_api_key

    os.environ["MAP_PROVIDER"] = map_provider
    os.environ["MAP_LANGUAGE"] = map_language
    os.environ["MAP_REGION"] = map_region
    app.config["MAP_PROVIDER"] = map_provider
    app.config["MAP_LANGUAGE"] = map_language
    app.config["MAP_REGION"] = map_region

    save_runtime_settings(
        {
            "GARMIN_USERNAME": username,
            "GARMIN_PASSWORD": password,
            "GARMIN_START_DATE": start_date,
            "MAP_PROVIDER": map_provider,
            "GOOGLE_MAPS_API_KEY": google_maps_api_key,
            "MAP_LANGUAGE": map_language,
            "MAP_REGION": map_region,
        }
    )

    if not username and not password and not start_date and not google_maps_api_key:
        flash("Keine Garmin-Daten eingegeben.", "error")
    else:
        flash("Einstellungen gespeichert (Garmin + Karte).", "success")

    # Try immediate Garmin login/import so real data is available right away.
    if username and password:
        try:
            stage_count = import_from_garmin()
            save_runtime_settings(
                {
                    "GARMIN_LAST_IMPORT_STATUS": "success",
                    "GARMIN_LAST_IMPORT_AT": _iso_now(),
                    "GARMIN_LAST_ERROR": "",
                    "GARMIN_NEXT_RETRY_AT": "",
                }
            )
            flash(f"Garmin-Anmeldung erfolgreich. {stage_count} Etappen wurden sofort geladen.", "success")
        except Exception as exc:
            msg = str(exc)
            if "429" in msg:
                retry_at = (_utcnow() + timedelta(minutes=GARMIN_IMPORT_COOLDOWN_MINUTES)).isoformat()
                save_runtime_settings(
                    {
                        "GARMIN_LAST_IMPORT_STATUS": "rate_limited",
                        "GARMIN_LAST_IMPORT_AT": _iso_now(),
                        "GARMIN_LAST_ERROR": msg,
                        "GARMIN_NEXT_RETRY_AT": retry_at,
                    }
                )
                flash("Garmin-Anmeldung erreicht aktuell ein API-Limit (429). Bitte in einigen Minuten erneut versuchen.", "error")
            else:
                save_runtime_settings(
                    {
                        "GARMIN_LAST_IMPORT_STATUS": "error",
                        "GARMIN_LAST_IMPORT_AT": _iso_now(),
                        "GARMIN_LAST_ERROR": msg,
                        "GARMIN_NEXT_RETRY_AT": "",
                    }
                )
                flash(f"Garmin-Anmeldung/Import fehlgeschlagen: {msg}", "error")
    return redirect(url_for("settings"))

@app.route("/demo/import", methods=["POST"])
def import_demo():
    create_demo_data(force=True)
    flash("Demo-Daten wurden aktualisiert.", "success")
    return redirect(url_for("index"))


@app.route("/garmin/import", methods=["POST"])
def import_garmin():
    runtime = load_runtime_settings()
    status = get_garmin_import_status(runtime)
    if status["cooldown_active"]:
        flash(
            f"Garmin-Import pausiert wegen API-Limit. Nächster Versuch in ca. {status['retry_in_minutes']} Min.",
            "error",
        )
        return redirect(url_for("settings"))

    try:
        stage_count = import_from_garmin()
        save_runtime_settings(
            {
                "GARMIN_LAST_IMPORT_STATUS": "success",
                "GARMIN_LAST_IMPORT_AT": _iso_now(),
                "GARMIN_LAST_ERROR": "",
                "GARMIN_NEXT_RETRY_AT": "",
            }
        )
        flash(f"Garmin-Import erfolgreich: {stage_count} Etappen aktualisiert.", "success")
    except Exception as exc:
        msg = str(exc)
        if "429" in msg:
            retry_at = (_utcnow() + timedelta(minutes=GARMIN_IMPORT_COOLDOWN_MINUTES)).isoformat()
            save_runtime_settings(
                {
                    "GARMIN_LAST_IMPORT_STATUS": "rate_limited",
                    "GARMIN_LAST_IMPORT_AT": _iso_now(),
                    "GARMIN_LAST_ERROR": msg,
                    "GARMIN_NEXT_RETRY_AT": retry_at,
                }
            )
            flash("Garmin-Import fehlgeschlagen: API-Limit (429). Bitte etwas warten und später erneut importieren.", "error")
        elif "Anmeldedaten fehlen" in msg:
            save_runtime_settings(
                {
                    "GARMIN_LAST_IMPORT_STATUS": "missing_credentials",
                    "GARMIN_LAST_IMPORT_AT": _iso_now(),
                    "GARMIN_LAST_ERROR": msg,
                    "GARMIN_NEXT_RETRY_AT": "",
                }
            )
            flash("Garmin-Import fehlgeschlagen: Bitte zuerst Garmin-Zugangsdaten in den Einstellungen speichern.", "error")
        else:
            save_runtime_settings(
                {
                    "GARMIN_LAST_IMPORT_STATUS": "error",
                    "GARMIN_LAST_IMPORT_AT": _iso_now(),
                    "GARMIN_LAST_ERROR": msg,
                    "GARMIN_NEXT_RETRY_AT": "",
                }
            )
            flash(f"Garmin-Import fehlgeschlagen: {msg}", "error")
    return redirect(url_for("settings"))


@app.route("/garmin/tokens", methods=["POST"])
def upload_garmin_tokens():
    """Accept a garmin_tokens.zip (from Colab) and extract it to data/garmin_tokens/."""
    import zipfile
    import io
    file = request.files.get("tokens_zip")
    if not file or file.filename == "":
        flash("Bitte eine garmin_tokens.zip Datei auswählen.", "error")
        return redirect(url_for("settings"))
    if not file.filename.lower().endswith(".zip"):
        flash("Nur .zip Dateien erlaubt.", "error")
        return redirect(url_for("settings"))
    try:
        from pathlib import Path
        token_dir = Path(Config.DATA_DIR) / "garmin_tokens"
        token_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(file.read())) as zf:
            for member in zf.namelist():
                # Only extract .json files directly into token_dir (no subdirs)
                name = Path(member).name
                if name.endswith(".json") and name:
                    data = zf.read(member)
                    (token_dir / name).write_bytes(data)
        flash("Garmin-Tokens gespeichert. Starte jetzt den Garmin-Import.", "success")
        # Clear any rate-limit cooldown so import can proceed immediately
        save_runtime_settings({"GARMIN_NEXT_RETRY_AT": "", "GARMIN_LAST_IMPORT_STATUS": ""})
    except Exception as exc:
        flash(f"Token-Upload fehlgeschlagen: {exc}", "error")
    return redirect(url_for("settings"))


@app.route("/colab/import", methods=["POST"])
def import_colab_json():
    file = request.files.get("colab_json")
    if not file or file.filename == "":
        flash("Bitte eine Colab-Exportdatei (JSON) auswaehlen.", "error")
        return redirect(url_for("settings"))

    filename = file.filename.lower()
    if not filename.endswith(".json"):
        flash("Ungueltiges Dateiformat. Bitte eine JSON-Datei hochladen.", "error")
        return redirect(url_for("settings"))

    try:
        payload = json.load(file)
        stage_count = import_from_colab_json(payload)
        save_runtime_settings(
            {
                "GARMIN_LAST_IMPORT_STATUS": "colab_import_success",
                "GARMIN_LAST_IMPORT_AT": _iso_now(),
                "GARMIN_LAST_ERROR": "",
                "GARMIN_NEXT_RETRY_AT": "",
            }
        )
        flash(f"Colab-Import erfolgreich: {stage_count} Etappen importiert.", "success")
    except Exception as exc:
        save_runtime_settings(
            {
                "GARMIN_LAST_IMPORT_STATUS": "colab_import_error",
                "GARMIN_LAST_IMPORT_AT": _iso_now(),
                "GARMIN_LAST_ERROR": str(exc),
            }
        )
        flash(f"Colab-Import fehlgeschlagen: {exc}", "error")

    return redirect(url_for("settings"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
