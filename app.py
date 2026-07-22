import json
import logging
import os
import threading
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
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
    import_from_json,
    save_stage_geocoding,
    get_stage_geocoding,
    get_stages_needing_geocoding,
)
from bikepacking.runtime_settings import load_runtime_settings, save_runtime_settings
import bikepacking.strava_client as strava_client
import bikepacking.strava_import as strava_import
from bikepacking.geocoding import enrich_stage_geocoding

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = app.config.get("SECRET_KEY", "change-me-locally")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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


def _geocode_pending_stages():
    """
    Background task: geocode all stages that have a track but no pass/country
    data yet. Runs sequentially with a short delay to be polite to Nominatim.
    Safe to call multiple times – already-geocoded stages are skipped.
    """
    stages = get_stages_needing_geocoding()
    if not stages:
        return
    logger.info("Auto-geocoding: %d stage(s) pending", len(stages))
    for stage in stages:
        stage_id = stage["id"]
        try:
            result = enrich_stage_geocoding(stage)
            save_stage_geocoding(stage_id, result["passes"], result["countries"])
            logger.info(
                "Auto-geocoding done for stage %s '%s': passes=%s countries=%s",
                stage_id, stage.get("title", "?"), result["passes"], result["countries"],
            )
        except Exception as exc:
            logger.error("Auto-geocoding error for stage %s: %s", stage_id, exc)


def _start_auto_geocoding():
    """Spawn a daemon thread that geocodes all pending stages."""
    t = threading.Thread(target=_geocode_pending_stages, daemon=True)
    t.start()
    return t


# Geocode any stages that were already in the DB but not yet geocoded
_start_auto_geocoding()


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


def get_tile_layer_config():
    runtime = load_runtime_settings()
    provider = (runtime.get("MAP_PROVIDER") or app.config.get("MAP_PROVIDER", "osm")).lower()
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

    return {
        "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": "&copy; OpenStreetMap contributors",
        "max_zoom": 19,
        "provider": "osm",
        "status": "OpenStreetMap aktiv",
        "mode": "osm",
    }


@app.route("/")
def index():
    tour = get_tour()
    stages = get_stages()
    summary = get_tour_summary()
    all_tracks_geojson = get_all_stages_geojson(stages)
    tile_layer = get_tile_layer_config()
    return render_template(
        "index.html",
        tour=tour,
        stages=stages,
        summary=summary,
        all_tracks_geojson=json.dumps(all_tracks_geojson),
        tile_layer=tile_layer,
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
    geocoding = get_stage_geocoding(stage)
    return render_template(
        "stage.html",
        stage=stage,
        photos=photos,
        track_geojson=json.dumps(track_geojson),
        tile_layer=tile_layer,
        geocoding=geocoding,
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
    tour = get_tour()
    strava_tokens = strava_client._load_tokens()
    return render_template(
        "settings.html",
        map_provider=runtime.get("MAP_PROVIDER", app.config.get("MAP_PROVIDER", "osm")),
        google_maps_api_key=runtime.get("GOOGLE_MAPS_API_KEY", ""),
        map_language=runtime.get("MAP_LANGUAGE", app.config.get("MAP_LANGUAGE", "de-DE")),
        map_region=runtime.get("MAP_REGION", app.config.get("MAP_REGION", "AT")),
        demo_mode=app.config["DEMO_MODE"],
        tour=tour,
        strava_configured=strava_client.is_configured(),
        strava_connected=strava_client.is_connected(),
        strava_athlete_id=strava_tokens["athlete_id"] if strava_tokens else None,
    )


@app.route("/settings/map", methods=["POST"])
def save_map_settings():
    current = load_runtime_settings()
    map_provider = request.form.get("map_provider", "").strip() or current.get("MAP_PROVIDER", "osm")
    google_maps_api_key = request.form.get("google_maps_api_key", "").strip() or current.get("GOOGLE_MAPS_API_KEY", "")
    map_language = request.form.get("map_language", "").strip() or current.get("MAP_LANGUAGE", "de-DE")
    map_region = request.form.get("map_region", "").strip() or current.get("MAP_REGION", "AT")

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
            "MAP_PROVIDER": map_provider,
            "GOOGLE_MAPS_API_KEY": google_maps_api_key,
            "MAP_LANGUAGE": map_language,
            "MAP_REGION": map_region,
        }
    )
    flash("Karteneinstellungen gespeichert.", "success")
    return redirect(url_for("settings"))


@app.route("/demo/import", methods=["POST"])
def import_demo():
    create_demo_data(force=True)
    flash("Demo-Daten wurden aktualisiert.", "success")
    return redirect(url_for("index"))


@app.route("/import/json", methods=["POST"])
def import_json():
    """Import tour + stages from an uploaded Colab/Garmin JSON export file."""
    file = request.files.get("json_file")
    if not file or file.filename == "":
        flash("Keine Datei ausgewählt.", "error")
        return redirect(url_for("settings"))
    if not file.filename.lower().endswith(".json"):
        flash("Nur JSON-Dateien werden akzeptiert.", "error")
        return redirect(url_for("settings"))

    try:
        raw = file.read().decode("utf-8")
        data = json.loads(raw)
    except Exception as exc:
        flash(f"Fehler beim Lesen der JSON-Datei: {exc}", "error")
        return redirect(url_for("settings"))

    counts = import_from_json(data)
    msg = (
        f"Import abgeschlossen: {counts['inserted']} neue Etappen"
        + (f", {counts['skipped']} übersprungen" if counts["skipped"] else "")
        + (f", {counts['errors']} Fehler" if counts["errors"] else "")
        + ". Demo-Daten wurden entfernt."
    )
    if counts["inserted"]:
        msg += " Pass- und Ländererkennung läuft im Hintergrund."
    flash(msg, "success")
    if counts["inserted"]:
        _start_auto_geocoding()
    return redirect(url_for("index"))


@app.route("/stage/<int:stage_id>/geocode", methods=["POST"])
def geocode_stage(stage_id):
    """Trigger pass + country detection for a single stage (runs in background)."""
    stage = get_stage(stage_id)
    if not stage:
        flash("Etappe nicht gefunden.", "error")
        return redirect(url_for("index"))

    def _run():
        try:
            result = enrich_stage_geocoding(stage)
            save_stage_geocoding(stage_id, result["passes"], result["countries"])
            logger.info(
                "Geocoding done for stage %s: passes=%s countries=%s",
                stage_id, result["passes"], result["countries"],
            )
        except Exception as exc:
            logger.error("Geocoding error for stage %s: %s", stage_id, exc)

    threading.Thread(target=_run, daemon=True).start()
    flash("Pass- und Ländererkennung läuft im Hintergrund. Seite in ~30 Sekunden neu laden.", "success")
    return redirect(url_for("stage_detail", stage_id=stage_id))



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
        inserted = counts.get("inserted", 0)
        updated = counts.get("updated", 0)
        flash(
            f"Strava-Import abgeschlossen: {inserted} neu, "
            f"{updated} aktualisiert, {counts['skipped']} übersprungen"
            + (f", {counts['errors']} Fehler" if counts["errors"] else "")
            + (". Pass- und Ländererkennung läuft im Hintergrund." if inserted or updated else "") + ".",
            "success",
        )
        if inserted or updated:
            _start_auto_geocoding()
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
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        expected = Config.STRAVA_WEBHOOK_VERIFY_TOKEN
        if mode == "subscribe" and token == expected and challenge:
            return jsonify({"hub.challenge": challenge})
        logger.warning("Strava webhook GET: invalid verification request")
        return "Forbidden", 403

    try:
        event = request.get_json(force=True, silent=True) or {}
    except Exception:
        event = {}

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
                _geocode_pending_stages()
            elif aspect_type == "update":
                strava_import.handle_webhook_update(activity_id, owner_id, updates)
                _geocode_pending_stages()
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


@app.route("/manifest.webmanifest")
def pwa_manifest():
    return send_from_directory(app.static_folder, "manifest.webmanifest",
                               mimetype="application/manifest+json")


@app.route("/service-worker.js")
def pwa_service_worker():
    return send_from_directory(app.static_folder, "service-worker.js",
                               mimetype="application/javascript")


@app.route("/icons/<path:filename>")
def pwa_icons(filename):
    icons_dir = os.path.join(os.path.dirname(__file__), "icons")
    return send_from_directory(icons_dir, filename)
