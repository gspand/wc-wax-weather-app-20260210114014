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
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS stages (
            id INTEGER PRIMARY KEY,
            tour_id INTEGER NOT NULL,
            garmin_activity_id TEXT,
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
            color TEXT,
            diary_text TEXT,
            rating TEXT,
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
        """
    )
    conn.commit()
    conn.close()
