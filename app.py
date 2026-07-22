import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
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
import bikepacking.strava_client as strava_client
import bikepacking.strava_import as strava_import

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = app.config.get("SECRET_KEY", "change-me-locally")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GARMIN_IMPORT_COOLDOWN_MINUTES = 45

init_db()
create_demo_data()

# Alte grüne/schwach-sichtbare Farben durch kontrastreichere ersetzen
def _migrate_colors():
    replacements = {
        "#43a047": "#ff6f00",  # Grün → Orange
        "#8bc34a": "#ffd600",  # Hellgrün → Gelb
        "#009688": "#0288d1",  # Teal → Blau
        "#00acc1": "#e91e63",  # Cyan-Grün → Pink
        "#1e88e5": "#1565c0",  # Hellblau → Dunkelblau
        "#fb8c00": "#ff3d00",  # Hellorange → Tieforange
    }
    from bikepacking.database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    for old, new in replacements.items():
        cursor.execute("UPDATE stages SET color = ? WHERE color = ?", (new, old))
    conn.commit()
    conn.close()

_migrate_colors()

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

    files = request.files.getlist("photo")
    caption = request.form.get("caption", "").strip()
    files = [f for f in files if f and f.filename != ""]
    if not files:
        flash("Kein Bild ausgewählt.", "error")
        return redirect(url_for("stage_detail", stage_id=stage_id))

    saved_count = 0
    for file in files:
        if not allowed_file(file.filename):
            flash(f"{file.filename}: Nur JPG, PNG oder WEBP erlaubt.", "error")
            continue
        filename = secure_filename(file.filename)
        if save_stage_photo(stage_id, file, filename, caption):
            saved_count += 1

    if saved_count:
        flash(f"{saved_count} Bild(er) gespeichert.", "success")
    else:
        flash("Kein Bild konnte gespeichert werden.", "error")
    return redirect(url_for("stage_detail", stage_id=stage_id))

@app.route("/settings", methods=["GET"])
def settings():
    runtime = load_runtime_settings()
    garmin = GarminClient()
    garmin_import_status = get_garmin_import_status(runtime)
    tour = get_tour()
    strava_tokens = strava_client._load_tokens()
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
        tour=tour,
        strava_configured=strava_client.is_configured(),
        strava_connected=strava_client.is_connected(),
        strava_athlete_id=strava_tokens["athlete_id"] if strava_tokens else None,
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
                name = secure_filename(Path(member).name)
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


# ---------------------------------------------------------------------------
# Strava OAuth routes
# ---------------------------------------------------------------------------

@app.route("/strava/connect")
def strava_connect():
    """Redirect the user to the Strava authorization page."""
    if not strava_client.is_configured():
        flash(
            "Strava ist nicht konfiguriert. Bitte STRAVA_CLIENT_ID, "
            "STRAVA_CLIENT_SECRET und STRAVA_CALLBACK_URL als Umgebungsvariablen setzen.",
            "error",
        )
        return redirect(url_for("settings"))
    auth_url = strava_client.get_authorization_url()
    return redirect(auth_url)


@app.route("/strava/callback")
def strava_callback():
    """Handle the OAuth callback from Strava."""
    error = request.args.get("error")
    if error:
        flash(f"Strava-Anmeldung abgebrochen: {error}", "error")
        return redirect(url_for("settings"))

    code = request.args.get("code")
    if not code:
        flash("Strava-Anmeldung fehlgeschlagen: kein Code erhalten.", "error")
        return redirect(url_for("settings"))

    try:
        athlete_id = strava_client.exchange_code_for_tokens(code)
        flash(
            f"Strava erfolgreich verbunden (Athlet-ID: {athlete_id}). "
            "Jetzt einen Zeitraum für den ersten Import auswählen.",
            "success",
        )
    except Exception as exc:
        logger.error("Strava OAuth callback error: %s", exc)
        flash("Strava-Verbindung fehlgeschlagen. Bitte erneut versuchen.", "error")
    return redirect(url_for("settings"))


@app.route("/strava/disconnect", methods=["POST"])
def strava_disconnect():
    """Remove stored Strava tokens (disconnect)."""
    strava_client.delete_tokens()
    flash("Strava-Konto getrennt. Bestehende Reisedaten bleiben erhalten.", "success")
    return redirect(url_for("settings"))


@app.route("/strava/import", methods=["POST"])
def strava_import_route():
    """Trigger the initial Strava bulk import for a tour and date range."""
    if not strava_client.is_connected():
        flash("Bitte zuerst Strava verbinden.", "error")
        return redirect(url_for("settings"))

    tour = get_tour()
    if not tour:
        flash("Keine Tour vorhanden. Bitte zuerst eine Tour anlegen.", "error")
        return redirect(url_for("settings"))

    start_date = request.form.get("strava_start_date", "").strip()
    end_date = request.form.get("strava_end_date", "").strip()

    if not start_date or not end_date:
        flash("Bitte Start- und Enddatum für den Strava-Import angeben.", "error")
        return redirect(url_for("settings"))

    if start_date > end_date:
        flash("Startdatum muss vor dem Enddatum liegen.", "error")
        return redirect(url_for("settings"))

    try:
        counts = strava_import.import_strava_for_tour(
            tour_id=tour["id"],
            start_date_str=start_date,
            end_date_str=end_date,
        )
        flash(
            f"Strava-Import abgeschlossen: {counts['inserted']} neu, "
            f"{counts['updated']} aktualisiert, {counts['skipped']} übersprungen"
            + (f", {counts['errors']} Fehler" if counts["errors"] else "") + ".",
            "success",
        )
    except Exception as exc:
        logger.error("Strava import error: %s", exc)
        flash(f"Strava-Import fehlgeschlagen: {exc}", "error")

    return redirect(url_for("settings"))


# ---------------------------------------------------------------------------
# Strava webhook endpoint
# ---------------------------------------------------------------------------

@app.route("/strava/webhook", methods=["GET", "POST"])
def strava_webhook():
    """
    GET  – Strava hub challenge verification.
    POST – Receive activity events; respond immediately, process in background.
    """
    if request.method == "GET":
        # Hub challenge verification
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        expected = Config.STRAVA_WEBHOOK_VERIFY_TOKEN
        if mode == "subscribe" and token == expected and challenge:
            return jsonify({"hub.challenge": challenge})
        logger.warning("Strava webhook GET: invalid verification request")
        return "Forbidden", 403

    # POST – event notification
    try:
        event = request.get_json(force=True, silent=True) or {}
    except Exception:
        event = {}

    # Respond immediately (Strava requires < 2 s response)
    threading.Thread(target=_process_webhook_event, args=(event,), daemon=True).start()
    return "OK", 200


def _process_webhook_event(event):
    """Process a Strava webhook event in a background thread."""
    try:
        object_type = event.get("object_type")
        aspect_type = event.get("aspect_type")
        activity_id = event.get("object_id")
        owner_id = event.get("owner_id")
        updates = event.get("updates", {})

        logger.info(
            "Strava webhook event: object_type=%s aspect_type=%s activity=%s",
            object_type, aspect_type, activity_id,
        )

        if object_type == "activity":
            if aspect_type == "create":
                strava_import.handle_webhook_create(activity_id, owner_id)
            elif aspect_type == "update":
                strava_import.handle_webhook_update(activity_id, owner_id, updates)
            elif aspect_type == "delete":
                strava_import.handle_webhook_delete(activity_id, owner_id)
            else:
                logger.info("Strava webhook: unknown aspect_type '%s', ignoring", aspect_type)

        elif object_type == "athlete" and aspect_type == "update":
            if updates.get("authorized") == "false":
                strava_import.handle_webhook_deauthorize(owner_id)

        else:
            logger.info(
                "Strava webhook: unhandled object_type='%s', ignoring", object_type
            )

    except Exception as exc:
        logger.error("Error processing Strava webhook event: %s", exc, exc_info=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
