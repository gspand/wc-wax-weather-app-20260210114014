import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "garminconnect", "curl_cffi", "ua-generator"], check=True)

import os, json, shutil, time
from datetime import datetime
from collections import defaultdict
from garminconnect import Garmin

# ── Zugangsdaten ──────────────────────────────────────────────────────────────
EMAIL      = "gspandljan@gmail.com"
PASSWORD   = "JamesbondOO7"
START_DATE = "2026-06-27"
TOUR_NAME  = "Dolomiten Bikepacking 2026"
COLORS     = ["#e53935", "#1e88e5", "#43a047", "#8e44ad", "#fb8c00", "#00acc1"]

# ── Login ─────────────────────────────────────────────────────────────────────
api = Garmin(EMAIL, PASSWORD)
api.login()
print("✅ Login erfolgreich")

# ── Tokens speichern und herunterladen ────────────────────────────────────────
token_dir = "/content/garmin_tokens_export"
os.makedirs(token_dir, exist_ok=True)
api.garth.dump(token_dir)
shutil.make_archive("/content/garmin_tokens", "zip", token_dir)
try:
    from google.colab import files
    files.download("/content/garmin_tokens.zip")
    print("📥 garmin_tokens.zip heruntergeladen → App: Einstellungen → Token hochladen")
except ImportError:
    print("garmin_tokens.zip gespeichert (lokal)")

# ── Alle Aktivitäten laden ────────────────────────────────────────────────────
print("Lade Aktivitäten...")
activities, start = [], 0
while True:
    batch = api.get_activities(start, 100)
    if not batch:
        break
    activities.extend(batch)
    start += len(batch)
    print(f"  {len(activities)} geladen...")
print(f"Fertig: {len(activities)} Aktivitäten")

# ── Radfahrten ab Startdatum filtern ─────────────────────────────────────────
CYCLING = {"road_biking", "cycling", "gravel_cycling", "mountain_biking"}
start_dt = datetime.strptime(START_DATE, "%Y-%m-%d")

tour_activities = [
    a for a in activities
    if datetime.strptime(a["startTimeLocal"], "%Y-%m-%d %H:%M:%S") >= start_dt
    and (a.get("activityType") or {}).get("typeKey", "") in CYCLING
]
tour_activities.sort(key=lambda a: a["startTimeLocal"])

days = defaultdict(list)
for a in tour_activities:
    days[a["startTimeLocal"][:10]].append(a)

# ── Trackpunkte laden ─────────────────────────────────────────────────────────
def get_track_points(activity_id):
    details = api.get_activity_details(activity_id)
    pts = []
    for p in details.get("activityDetailMetrics", []):
        lat = p.get("directLatitude") or p.get("latitude")
        lon = p.get("directLongitude") or p.get("longitude")
        if lat is not None and lon is not None:
            pts.append([float(lat), float(lon)])
    if not pts:
        for p in (details.get("geoPolylineDTO") or {}).get("polyline", []):
            lat = p.get("lat") or p.get("latitude")
            lon = p.get("lon") or p.get("longitude")
            if lat is not None and lon is not None:
                pts.append([float(lat), float(lon)])
    return pts

# ── Etappen verarbeiten ───────────────────────────────────────────────────────
stages = []
for idx, (day, acts) in enumerate(sorted(days.items())):
    pts_all = []
    for a in acts:
        print(f"  Lade: {a['startTimeLocal']}  {a['activityName']}")
        pts = get_track_points(a["activityId"])
        print(f"    {len(pts)} Trackpunkte")
        pts_all.extend(pts)
        time.sleep(0.2)

    stages.append({
        "day":      day,
        "acts":     acts,
        "color":    COLORS[idx % len(COLORS)],
        "points":   pts_all,
        "title":    acts[0].get("activityName", f"Tag {idx+1}"),
        "distance": round(sum((a.get("distance") or 0) for a in acts) / 1000, 1),
        "elevation": round(sum((a.get("elevationGain") or 0) for a in acts)),
        "tss":      round(sum((a.get("trainingStressScore") or 0) for a in acts), 1),
    })

print(f"\n✅ {len(stages)} Etappen verarbeitet")

# ── JSON für die App exportieren ──────────────────────────────────────────────
stages_export = []
for s in stages:
    acts = s["acts"]
    avg_hr = [float(a["averageHR"]) for a in acts if a.get("averageHR")]
    max_hr = [float(a["maxHR"])     for a in acts if a.get("maxHR")]
    avg_pw = [float(a["averagePower"]) for a in acts if a.get("averagePower")]
    np_pw  = [float(a.get("normPower") or a.get("normalizedPower") or 0)
              for a in acts if a.get("normPower") or a.get("normalizedPower")]
    stages_export.append({
        "date":               s["day"],
        "title":              s["title"],
        "garmin_activity_id": ",".join(str(a["activityId"]) for a in acts if a.get("activityId")),
        "distance":           s["distance"],
        "elevation_gain":     s["elevation"],
        "moving_time":        int(sum(float(a.get("movingDuration")  or 0) for a in acts)),
        "elapsed_time":       int(sum(float(a.get("elapsedDuration") or 0) for a in acts)),
        "average_hr":         round(sum(avg_hr)/len(avg_hr), 1) if avg_hr else None,
        "max_hr":             max(max_hr) if max_hr else None,
        "average_power":      round(sum(avg_pw)/len(avg_pw), 1) if avg_pw else None,
        "normalized_power":   round(sum(np_pw)/len(np_pw),  1) if np_pw  else None,
        "load_score":         s["tss"],
        "track_points":       s["points"],
    })

payload = {
    "tour":   {"name": TOUR_NAME, "start_date": START_DATE, "description": "Garmin Export"},
    "stages": stages_export,
}
with open("bikepacking_colab_export.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
print(f"✅ bikepacking_colab_export.json gespeichert ({len(stages_export)} Etappen)")

try:
    from google.colab import files
    files.download("bikepacking_colab_export.json")
    print("📥 bikepacking_colab_export.json heruntergeladen → App: Einstellungen → Colab JSON importieren")
except ImportError:
    print("bikepacking_colab_export.json gespeichert (lokal)")
