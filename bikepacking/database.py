import sqlite3
from pathlib import Path

from config import Config


def get_connection():
    db_path = Path(Config.DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS tours (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS stages (
            id INTEGER PRIMARY KEY,
            tour_id INTEGER NOT NULL,
            garmin_activity_id TEXT,
            source TEXT DEFAULT 'manual',
            external_activity_id TEXT,
            date TEXT NOT NULL,
            title TEXT NOT NULL,
            distance REAL DEFAULT 0,
            elevation_gain REAL DEFAULT 0,
            moving_time INTEGER DEFAULT 0,
            elapsed_time INTEGER DEFAULT 0,
            average_hr REAL,
            max_hr REAL,
            average_power REAL,
            normalized_power REAL,
            load_score REAL,
            average_speed REAL,
            max_speed REAL,
            average_cadence REAL,
            temperature REAL,
            color TEXT,
            diary_text TEXT,
            rating TEXT,
            is_rest_day INTEGER DEFAULT 0,
            location TEXT,
            passes TEXT,
            countries TEXT,
            track_geojson TEXT,
            FOREIGN KEY(tour_id) REFERENCES tours(id)
        );

        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY,
            stage_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            caption TEXT,
            FOREIGN KEY(stage_id) REFERENCES stages(id)
        );

        CREATE TABLE IF NOT EXISTS strava_tokens (
            id INTEGER PRIMARY KEY,
            athlete_id TEXT,
            access_token TEXT,
            refresh_token TEXT,
            expires_at INTEGER,
            scope TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    conn.commit()
    _migrate_schema(conn)
    conn.close()


def _migrate_schema(conn):
    """Apply incremental schema migrations for existing databases."""
    cursor = conn.cursor()

    # tours: add end_date if missing
    _add_column_if_missing(cursor, "tours", "end_date", "TEXT")

    # stages: add new Strava-related and rest-day columns if missing
    _add_column_if_missing(cursor, "stages", "source", "TEXT DEFAULT 'manual'")
    _add_column_if_missing(cursor, "stages", "external_activity_id", "TEXT")
    _add_column_if_missing(cursor, "stages", "average_speed", "REAL")
    _add_column_if_missing(cursor, "stages", "max_speed", "REAL")
    _add_column_if_missing(cursor, "stages", "average_cadence", "REAL")
    _add_column_if_missing(cursor, "stages", "temperature", "REAL")
    _add_column_if_missing(cursor, "stages", "is_rest_day", "INTEGER DEFAULT 0")
    _add_column_if_missing(cursor, "stages", "location", "TEXT")
    _add_column_if_missing(cursor, "stages", "passes", "TEXT")
    _add_column_if_missing(cursor, "stages", "countries", "TEXT")

    # Unique index for idempotent Strava imports
    # Covers rows where source is a non-manual, non-empty value with an external ID
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_stages_source_external
        ON stages (source, external_activity_id)
        WHERE source IS NOT NULL AND external_activity_id IS NOT NULL
              AND external_activity_id != ''
        """
    )

    conn.commit()


def _add_column_if_missing(cursor, table, column, column_def):
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row["name"] for row in cursor.fetchall()}
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")
