# Bikepacking Diary – Deployment auf Hetzner

> **Wichtig:** Dieser Stack ist vollständig von SkyBase isoliert.  
> Alle Ressourcen tragen das Präfix `bpdiary_`.  
> Kein SkyBase-Container, kein Netzwerk, kein Volume wird verändert.

---

## Inhaltsverzeichnis

1. [Architektur-Übersicht](#1-architektur-übersicht)
2. [Verzeichnisstruktur](#2-verzeichnisstruktur)
3. [Ports](#3-ports)
4. [Umgebungsvariablen](#4-umgebungsvariablen)
5. [Lokale Änderungen prüfen und committen](#5-lokale-änderungen-prüfen-und-committen)
6. [Server-Analyse (nur lesend)](#6-server-analyse-nur-lesend)
7. [Repository auf dem Server aktualisieren](#7-repository-auf-dem-server-aktualisieren)
8. [Deployment vorbereiten](#8-deployment-vorbereiten)
9. [Konfiguration prüfen](#9-konfiguration-prüfen)
10. [Images bauen](#10-images-bauen)
11. [Stack starten](#11-stack-starten)
12. [Status und Logs prüfen](#12-status-und-logs-prüfen)
13. [Healthcheck testen](#13-healthcheck-testen)
14. [Stack stoppen (ohne Datenverlust)](#14-stack-stoppen-ohne-datenverlust)
15. [Stack aktualisieren](#15-stack-aktualisieren)
16. [Reverse Proxy (kontrollierter Schritt)](#16-reverse-proxy-kontrollierter-schritt)
17. [Backup und Restore](#17-backup-und-restore)
18. [DNS-Eintrag](#18-dns-eintrag)
19. [Offene Punkte und Sicherheitsmaßnahmen](#19-offene-punkte-und-sicherheitsmaßnahmen)
20. [Nächste Schritte Backend und Benutzerverwaltung](#20-nächste-schritte-backend-und-benutzerverwaltung)
21. [Risiken für SkyBase](#21-risiken-für-skybase)

---

## 1. Architektur-Übersicht

```
Internet
  │
  ▼
[DNS: diary-api.skybasevario.com → 178.104.230.235]
  │
  ▼
[Host: 178.104.230.235]
  │
  ├─── Bestehende SkyBase-Infrastruktur (UNVERÄNDERT)
  │
  └─── Bikepacking Diary Stack (NEU, isoliert)
         │
         ├── bpdiary_nginx   (Port 127.0.0.1:8081 → intern :80)
         │      │ proxy_pass
         │      ▼
         ├── bpdiary_api     (intern :5000, Flask/Gunicorn)
         │      │ psycopg2
         │      ▼
         ├── bpdiary_postgres (intern :5432, PostgreSQL 16)
         └── bpdiary_backup  (Cron, täglich 02:00 Uhr)
```

### Docker-Netzwerk

| Name              | Typ    | Subnet          | Zweck                      |
|-------------------|--------|-----------------|----------------------------|
| `bpdiary_internal`| bridge | 172.30.0.0/24   | Interne Kommunikation       |

> **Vor dem Start prüfen**, ob 172.30.0.0/24 auf dem Server bereits vergeben ist:
> ```bash
> docker network ls
> docker network inspect <netzwerk-name>
> ```

### Volumes

| Name                  | Inhalt                      |
|-----------------------|-----------------------------|
| `bpdiary_pgdata`      | PostgreSQL-Datenbankdateien |
| `bpdiary_photos`      | Hochgeladene Fotos          |
| `bpdiary_gpx`         | GPX-Tracks                  |
| `bpdiary_photobooks`  | Generierte Fotobücher       |
| `bpdiary_backups`     | Backup-Archive              |
| `bpdiary_letsencrypt` | TLS-Zertifikate (Nginx)     |

---

## 2. Verzeichnisstruktur

```
deploy/bikepacking-diary/
├── docker-compose.yml     # Eigener Stack
├── Dockerfile             # Multi-Stage Build für Flask-API
├── nginx.conf             # Reverse-Proxy-Konfiguration
├── .env.example           # Vorlage für Secrets (NIEMALS committen)
├── .env                   # Secrets (gitignore, nur auf Server)
├── backup/
│   └── backup.sh          # Backup-Skript (DB + Medien)
└── README.md              # Diese Dokumentation
```

---

## 3. Ports

| Container         | Intern | Extern (Host)         | Öffentlich? |
|-------------------|--------|-----------------------|-------------|
| `bpdiary_nginx`   | 80     | 127.0.0.1:8081        | Nein (nur localhost) |
| `bpdiary_api`     | 5000   | –                     | Nein        |
| `bpdiary_postgres`| 5432   | –                     | Nein        |

> Port 8081 ist nur auf `127.0.0.1` gebunden. Der bestehende Host-Nginx oder  
> Traefik/Caddy von SkyBase leitet von außen an `127.0.0.1:8081` weiter.  
> Erst nach manueller Prüfung der Port-Belegung aktivieren (Schritt 6).

---

## 4. Umgebungsvariablen

Alle Werte stehen in `.env` (aus `.env.example` erzeugt).

| Variable                     | Pflicht | Beschreibung                          |
|------------------------------|---------|---------------------------------------|
| `POSTGRES_DB`                | Ja      | Datenbankname (Standard: `bpdiary`)   |
| `POSTGRES_USER`              | Ja      | DB-Benutzer (Standard: `bpdiary`)     |
| `POSTGRES_PASSWORD`          | Ja      | Sicheres Passwort (kein Default)      |
| `SECRET_KEY`                 | Ja      | Flask Session Key                     |
| `FLASK_ENV`                  | Nein    | `production` (Standard)               |
| `DEMO_MODE`                  | Nein    | `false` (Standard)                    |
| `STRAVA_CLIENT_ID`           | Nein    | Strava API App ID                     |
| `STRAVA_CLIENT_SECRET`       | Nein    | Strava API Secret                     |
| `STRAVA_CALLBACK_URL`        | Nein    | OAuth Callback URL                    |
| `STRAVA_WEBHOOK_VERIFY_TOKEN`| Nein    | Webhook-Verifikationstoken            |
| `GARMIN_USERNAME`            | Nein    | Garmin Connect Login                  |
| `GARMIN_PASSWORD`            | Nein    | Garmin Connect Passwort               |
| `MAP_PROVIDER`               | Nein    | `osm` oder `google`                   |
| `GOOGLE_MAPS_API_KEY`        | Nein    | Google Maps API Key                   |

---

## 5. Lokale Änderungen prüfen und committen

```bash
# Geänderte Dateien prüfen
git status
git diff

# Deployment-Dateien committen
git add deploy/bikepacking-diary
git commit -m "Add isolated Bikepacking Diary deployment stack"
git push
```

---

## 6. Server-Analyse (nur lesend)

**Erst anmelden:**

```bash
ssh -i ~/.ssh/id_ed25519_skybase_mac janadmin@178.104.230.235
```

**Dann nur lesend analysieren – nichts verändern:**

```bash
# System
hostname
whoami
pwd

# Laufende Container (SkyBase und andere)
docker ps

# Netzwerke (auf Subnet-Konflikte prüfen)
docker network ls
docker network inspect $(docker network ls -q) 2>/dev/null | grep -E '"Name"|Subnet'

# Volumes
docker volume ls

# Alle aktiven Compose-Stacks
docker compose ls

# Belegte Ports (Firewall/System)
sudo ss -tulpn

# Festplatten
df -h

# RAM
free -h

# Bestehende Reverse-Proxy-Konfiguration feststellen
# (Wichtig: NICHT ändern – nur lesen)
which nginx caddy traefik 2>/dev/null || echo "Kein bekannter RP im PATH"
sudo nginx -T 2>/dev/null | head -100 || echo "Nginx nicht vorhanden oder kein Root-Zugriff"
docker ps --format '{{.Names}}: {{.Image}}' | grep -i -E 'nginx|traefik|caddy'
```

> ⚠️ **Vor jeder Änderung stoppen** und die geplante Änderung hier dokumentieren.

---

## 7. Repository auf dem Server aktualisieren

**Repository-Pfad finden** (nicht erfinden – auf dem Server ausführen):

```bash
find /home /opt -maxdepth 3 -type d -name .git 2>/dev/null
```

Das gibt einen Pfad zurück, z. B. `/opt/wc-wax-weather-app-20260210114014/.git`.  
Der Repository-Root ist dann `/opt/wc-wax-weather-app-20260210114014`.

**Repository aktualisieren:**

```bash
cd /PFAD_ZUM_REPOSITORY   # mit dem gefundenen Pfad ersetzen
git status
git pull
```

---

## 8. Deployment vorbereiten

```bash
cd /PFAD_ZUM_REPOSITORY/deploy/bikepacking-diary

# .env aus Vorlage erstellen
cp .env.example .env
chmod 600 .env

# Sichere Passwörter und Keys erzeugen
openssl rand -base64 32   # für POSTGRES_PASSWORD
openssl rand -hex 32      # für SECRET_KEY
openssl rand -hex 16      # für STRAVA_WEBHOOK_VERIFY_TOKEN

# .env bearbeiten und alle Werte eintragen
nano .env
```

---

## 9. Konfiguration prüfen

```bash
cd /PFAD_ZUM_REPOSITORY/deploy/bikepacking-diary

# Compose-Konfiguration validieren (zeigt interpolierte Werte)
docker compose config
```

Prüfen:
- Alle Passwörter sind gesetzt (kein leeres `POSTGRES_PASSWORD`)
- Netzwerk-Subnet 172.30.0.0/24 ist nicht vergeben
- Volumes haben den Präfix `bpdiary_`

---

## 10. Images bauen

```bash
cd /PFAD_ZUM_REPOSITORY/deploy/bikepacking-diary

# Nur eigene Images bauen – SkyBase wird nicht berührt
docker compose build
```

---

## 11. Stack starten

```bash
cd /PFAD_ZUM_REPOSITORY/deploy/bikepacking-diary

docker compose up -d
```

---

## 12. Status und Logs prüfen

```bash
# Status aller Container im Stack
docker compose ps

# Logs (letzte 100 Zeilen)
docker compose logs --tail=100

# Logs einzelner Services
docker compose logs api --tail=50
docker compose logs db --tail=50
docker compose logs nginx --tail=50
```

---

## 13. Healthcheck testen

Da kein Host-Port für die API nach außen exponiert ist, Test **innerhalb des Docker-Netzwerks**:

```bash
# Direkt im API-Container
docker compose exec api curl -s http://localhost:5000/health

# Über Nginx (Port 8081 nur auf localhost)
curl -s http://127.0.0.1:8081/health
```

Erwartete Antwort:

```json
{
  "status": "ok",
  "service": "bikepacking-diary-api"
}
```

---

## 14. Stack stoppen (ohne Datenverlust)

```bash
# Stoppt Container, löscht KEINE Volumes
docker compose down
```

> ⚠️ **Niemals** `docker compose down -v` verwenden – das löscht alle Volumes inkl. Daten.

---

## 15. Stack aktualisieren

```bash
cd /PFAD_ZUM_REPOSITORY

git pull

cd deploy/bikepacking-diary
docker compose build
docker compose up -d
```

---

## 16. Reverse Proxy (kontrollierter Schritt)

> ⚠️ **Dieser Schritt muss manuell und nach vorheriger Analyse durchgeführt werden.**  
> Bestehende SkyBase-Konfiguration darf nicht verändert werden.

**Vorher feststellen, welcher Reverse Proxy auf dem Server läuft:**

```bash
# Option A: Host-Nginx
sudo nginx -T

# Option B: Nginx in Docker
docker ps | grep nginx

# Option C: Traefik
docker ps | grep traefik

# Option D: Caddy
docker ps | grep caddy
```

**Dann – je nach Ergebnis – einen der folgenden Wege wählen:**

### Szenario A: Host-Nginx vorhanden

Neue Site-Konfiguration hinzufügen (separate Datei, nie bestehende überschreiben):

```bash
sudo nano /etc/nginx/sites-available/diary-api.skybasevario.com
```

Inhalt:

```nginx
server {
    listen 80;
    server_name diary-api.skybasevario.com;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/diary-api.skybasevario.com \
           /etc/nginx/sites-enabled/
sudo nginx -t        # Konfiguration testen
sudo nginx -s reload # Nur reloaden, nicht restarting
```

### Szenario B: Traefik oder Caddy (Docker-basiert)

Labels in `docker-compose.yml` ergänzen (separater Schritt nach Analyse).

### TLS / Let's Encrypt (erst nach DNS-Propagierung)

```bash
# Certbot für Host-Nginx
sudo certbot --nginx -d diary-api.skybasevario.com

# Dann nginx.conf HTTPS-Block aktivieren (Kommentare entfernen)
```

---

## 17. Backup und Restore

### Backup manuell starten

```bash
cd /PFAD_ZUM_REPOSITORY/deploy/bikepacking-diary
./backup/backup.sh
```

Oder im Backup-Container:

```bash
docker compose exec backup /backup.sh
```

Backups liegen im Volume `bpdiary_backups` unter `/backups/`.

### Backup-Dateien einsehen

```bash
docker compose run --rm backup ls -lah /backups/db/
docker compose run --rm backup ls -lah /backups/media/
```

### Datenbank wiederherstellen

```bash
# 1. API stoppen (nicht die DB)
docker compose stop api

# 2. Backup einspielen (Dateiname anpassen)
gunzip -c /backups/db/bpdiary_YYYYMMDD_HHMMSS.sql.gz | \
  docker compose exec -T db psql -U bpdiary -d bpdiary

# 3. API wieder starten
docker compose start api
```

### Medien wiederherstellen

```bash
# Fotos
docker compose run --rm backup \
  tar -xzf /backups/media/photos_YYYYMMDD_HHMMSS.tar.gz -C /data

# GPX
docker compose run --rm backup \
  tar -xzf /backups/media/gpx_YYYYMMDD_HHMMSS.tar.gz -C /data
```

> ⚠️ Restore nicht auf laufendem Produktionssystem ohne vorherige Datensicherung.

---

## 18. DNS-Eintrag

Bei deinem DNS-Provider (z. B. Cloudflare, IONOS, Hetzner DNS):

| Typ | Name       | Wert              | TTL  |
|-----|------------|-------------------|------|
| A   | diary-api  | 178.104.230.235   | 300  |

Vollständiger Hostname: `diary-api.skybasevario.com`

**DNS-Propagierung prüfen:**

```bash
dig diary-api.skybasevario.com A
nslookup diary-api.skybasevario.com
```

> DNS-Propagierung kann bis zu 24 Stunden dauern. TLS/Let's Encrypt erst  
> nach vollständiger Propagierung einrichten.

---

## 19. Offene Punkte und Sicherheitsmaßnahmen

| Punkt | Status | Aktion |
|-------|--------|--------|
| Bestehende Reverse-Proxy-Konfiguration feststellen | ⬜ Offen | Schritt 6 auf Server ausführen |
| Subnet 172.30.0.0/24 auf Konflikte prüfen | ⬜ Offen | `docker network ls` auf Server |
| Port 8081 Verfügbarkeit prüfen | ⬜ Offen | `sudo ss -tulpn` auf Server |
| DNS-Eintrag diary-api setzen | ⬜ Offen | DNS-Provider |
| TLS-Zertifikat (Let's Encrypt) | ⬜ Offen | Nach DNS-Propagierung |
| HTTPS-Block in nginx.conf aktivieren | ⬜ Offen | Nach TLS |
| Firewall: Port 443 freigeben | ⬜ Offen | `sudo ufw allow 443` (nach Prüfung) |
| Garmin-Passwort in .env: Sicherheit | ⬜ Offen | Garmin 2FA prüfen |
| Multi-User Benutzerverwaltung im Backend | ⬜ Offen | Siehe Schritt 20 |
| Backup-Offsite (z.B. S3/Hetzner Object Storage) | ⬜ Offen | Optional, empfohlen |

---

## 20. Nächste Schritte Backend und Benutzerverwaltung

Das Backend ist aktuell **single-user**. Für den Mehrbenutzerbetrieb:

1. **PostgreSQL-Migration:** SQLite → PostgreSQL (Alembic/Flask-Migrate)
2. **User-Tabelle:** `users` (id, email, password_hash, created_at)
3. **user_id Fremdschlüssel** in allen Tabellen (tours, stages, photos, geocoding)
4. **Authentifizierung:** JWT-Token (flask-jwt-extended) oder Session-basiert
5. **Strava-Tokens pro User** speichern (aktuell global)
6. **Datenisolation:** Alle Queries mit `WHERE user_id = current_user.id`
7. **Registrierung/Login-Endpunkte:** `POST /auth/register`, `POST /auth/login`
8. **Flutter-App:** HTTP-Client mit Bearer-Token

**Empfohlene Reihenfolge:**
1. Erst Flutter-MVP mit Single-User-Backend fertigstellen
2. Dann PostgreSQL-Migration
3. Dann User-Auth einbauen
4. Dann Multi-User auf Hetzner deployen

---

## 21. Risiken für SkyBase

| Risiko | Wahrscheinlichkeit | Schutzmaßnahme |
|--------|--------------------|----------------|
| Port-Konflikt (8081) | Gering | Schritt 6 vor Start prüfen |
| Subnet-Konflikt (172.30.0.0/24) | Gering | `docker network ls` prüfen |
| RAM-Engpass auf VPS | Mittel | Limits gesetzt; `free -h` überwachen |
| Nginx-Konfiguration versehentlich überschrieben | Gering | Nur neue Datei hinzufügen, nie ersetzen |
| `docker system prune` löscht SkyBase-Daten | Hoch | **Niemals** ohne Prüfung ausführen |
| Versehentlicher `compose down` des SkyBase-Stacks | Mittel | Immer `cd deploy/bikepacking-diary` vor compose-Befehlen |

> ✅ Alle `bpdiary_`-Präfixe sorgen dafür, dass SkyBase-Ressourcen  
> bei `docker compose`-Befehlen im Bikepacking-Verzeichnis nie berührt werden.
