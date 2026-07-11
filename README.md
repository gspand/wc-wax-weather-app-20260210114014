# Bikepacking Diary

Lokale Web-App mit Etappenübersicht, Garmin-Import und Kartenansicht.

## Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Danach im Browser öffnen:

http://127.0.0.1:5000

## Garmin Import

Für echten Import diese Variablen setzen:

```text
GARMIN_USERNAME=dein-login
GARMIN_PASSWORD=dein-passwort
GARMIN_START_DATE=2026-06-27
```

Dann in der App unter Einstellungen auf Garmin-Daten importieren.

## Google Terrain Tiles

Für Google Terrain Map Tiles API:

```text
MAP_PROVIDER=google
GOOGLE_MAPS_API_KEY=dein-google-api-key
MAP_LANGUAGE=de-DE
MAP_REGION=AT
```

Wenn kein API-Key gesetzt ist, fällt die App automatisch auf OpenStreetMap zurück.

Die Startseite zeigt eine Gesamtübersicht über alle Tage auf einer Karte.

## Colab Export-Import (ohne Garmin API-Limit im Container)

Wenn Garmin im Container mit 429 limitiert ist, kannst du in Colab exportieren und hier importieren:

1. In Colab das Skript aus [garmin/colab_export.py](garmin/colab_export.py) nutzen.
2. JSON-Datei erzeugen (`bikepacking_colab_export.json`).
3. In der App unter `/settings` bei "Colab-Export importieren" hochladen.

Akzeptierte JSON-Formate:

- `{"tour": {...}, "stages": [...]}`
- `{"activities": [...]}` (optional mit `track_points` je Aktivität)
