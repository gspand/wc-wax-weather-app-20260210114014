#!/bin/sh
# =============================================================================
# Bikepacking Diary – Backup-Skript
#
# Sichert:
#   1. PostgreSQL-Datenbank (pg_dump)
#   2. Foto-Verzeichnis
#   3. GPX-Verzeichnis
#   4. Fotobuch-Verzeichnis
#
# Backups werden mit Zeitstempel im Volume /backups abgelegt.
# Aufbewahrungsdauer: 30 Tage (konfigurierbar via BACKUP_RETENTION_DAYS).
#
# Ausführen: ./backup/backup.sh
# Automatisch: täglich um 02:00 Uhr durch den bpdiary_backup-Container
# =============================================================================

set -eu

# Konfiguration
BACKUP_DIR="/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

POSTGRES_HOST="${POSTGRES_HOST:-db}"
POSTGRES_DB="${POSTGRES_DB:-bpdiary}"
POSTGRES_USER="${POSTGRES_USER:-bpdiary}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

echo "================================================================"
echo "Bikepacking Diary Backup – $(date)"
echo "================================================================"

# Zielverzeichnis anlegen
mkdir -p "${BACKUP_DIR}/db"
mkdir -p "${BACKUP_DIR}/media"

# --- 1. Datenbank-Backup ---------------------------------------------------
DB_DUMP="${BACKUP_DIR}/db/bpdiary_${TIMESTAMP}.sql.gz"
echo "[1/4] Datenbank-Backup → ${DB_DUMP}"

pg_dump \
  -h "${POSTGRES_HOST}" \
  -U "${POSTGRES_USER}" \
  -d "${POSTGRES_DB}" \
  --no-password \
  --format=plain \
  --encoding=UTF8 \
  | gzip > "${DB_DUMP}"

echo "      ✓ Datenbank gesichert ($(du -sh "${DB_DUMP}" | cut -f1))"

# --- 2. Fotos-Backup --------------------------------------------------------
PHOTOS_ARCHIVE="${BACKUP_DIR}/media/photos_${TIMESTAMP}.tar.gz"
echo "[2/4] Fotos-Backup → ${PHOTOS_ARCHIVE}"

if [ -d "/data/photos" ] && [ "$(ls -A /data/photos 2>/dev/null)" ]; then
  tar -czf "${PHOTOS_ARCHIVE}" -C /data photos
  echo "      ✓ Fotos gesichert ($(du -sh "${PHOTOS_ARCHIVE}" | cut -f1))"
else
  echo "      ⚠ Keine Fotos vorhanden, übersprungen."
fi

# --- 3. GPX-Backup ----------------------------------------------------------
GPX_ARCHIVE="${BACKUP_DIR}/media/gpx_${TIMESTAMP}.tar.gz"
echo "[3/4] GPX-Backup → ${GPX_ARCHIVE}"

if [ -d "/data/gpx" ] && [ "$(ls -A /data/gpx 2>/dev/null)" ]; then
  tar -czf "${GPX_ARCHIVE}" -C /data gpx
  echo "      ✓ GPX-Dateien gesichert ($(du -sh "${GPX_ARCHIVE}" | cut -f1))"
else
  echo "      ⚠ Keine GPX-Dateien vorhanden, übersprungen."
fi

# --- 4. Fotobücher-Backup ---------------------------------------------------
PHOTOBOOKS_ARCHIVE="${BACKUP_DIR}/media/photobooks_${TIMESTAMP}.tar.gz"
echo "[4/4] Fotobücher-Backup → ${PHOTOBOOKS_ARCHIVE}"

if [ -d "/data/photobooks" ] && [ "$(ls -A /data/photobooks 2>/dev/null)" ]; then
  tar -czf "${PHOTOBOOKS_ARCHIVE}" -C /data photobooks
  echo "      ✓ Fotobücher gesichert ($(du -sh "${PHOTOBOOKS_ARCHIVE}" | cut -f1))"
else
  echo "      ⚠ Keine Fotobücher vorhanden, übersprungen."
fi

# --- Alte Backups löschen (Retention) --------------------------------------
echo ""
echo "Alte Backups löschen (älter als ${RETENTION_DAYS} Tage)..."
find "${BACKUP_DIR}" -type f \( -name "*.sql.gz" -o -name "*.tar.gz" \) \
  -mtime +${RETENTION_DAYS} -print -delete

echo ""
echo "================================================================"
echo "Backup abgeschlossen – $(date)"
echo "Speicherverbrauch: $(du -sh ${BACKUP_DIR} | cut -f1)"
echo "================================================================"

# --- Restore-Anleitung (Kommentar) -----------------------------------------
# 
# DATENBANK WIEDERHERSTELLEN:
#
#   1. Docker-Stack stoppen (API, nicht die DB):
#      docker compose stop api
#
#   2. Backup-Datei entpacken und einspielen:
#      gunzip -c /backups/db/bpdiary_YYYYMMDD_HHMMSS.sql.gz | \
#        docker compose exec -T db psql -U bpdiary -d bpdiary
#
#   3. API wieder starten:
#      docker compose start api
#
# MEDIEN WIEDERHERSTELLEN:
#
#   Fotos:
#     docker compose run --rm backup \
#       tar -xzf /backups/media/photos_YYYYMMDD_HHMMSS.tar.gz -C /data
#
#   GPX:
#     docker compose run --rm backup \
#       tar -xzf /backups/media/gpx_YYYYMMDD_HHMMSS.tar.gz -C /data
#
# WICHTIG: Restore niemals auf einem laufenden Produktionssystem ohne vorherige
#          Datensicherung durchführen.
