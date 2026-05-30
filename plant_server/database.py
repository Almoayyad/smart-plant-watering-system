"""
database.py — SQLite helper for plant sensor data.
Creates the database and table if they do not exist.
"""

import sqlite3
import os
import pandas as pd

# Allow overriding the DB path via environment variable (used in Docker)
DB_PATH = os.getenv("DB_PATH", "plant_data.db")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sensor_data (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    plant_id      TEXT,
    temperature_c REAL,
    pressure_hpa  REAL,
    light_lux     REAL,
    soil_raw      INTEGER,
    soil_state    TEXT,
    pump          TEXT,
    dry_threshold INTEGER,
    uptime_ms     INTEGER
);
"""


def get_connection():
    """Return a new SQLite connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the sensor_data table if it does not exist."""
    with get_connection() as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()
    print(f"[DB] Database ready: {DB_PATH}")


def insert_reading(data: dict):
    """
    Insert one sensor reading into sensor_data.
    data must be a dict matching the JSON fields from the ESP32.
    """
    sql = """
    INSERT INTO sensor_data
        (timestamp, plant_id, temperature_c, pressure_hpa,
         light_lux, soil_raw, soil_state, pump, dry_threshold, uptime_ms)
    VALUES
        (:timestamp, :plant_id, :temperature_c, :pressure_hpa,
         :light_lux, :soil_raw, :soil_state, :pump, :dry_threshold, :uptime_ms)
    """
    with get_connection() as conn:
        conn.execute(sql, data)
        conn.commit()


def get_recent_data(limit: int = 200) -> pd.DataFrame:
    """Return the most recent rows as a pandas DataFrame."""
    sql = f"""
    SELECT * FROM sensor_data
    ORDER BY id DESC
    LIMIT {limit}
    """
    with get_connection() as conn:
        df = pd.read_sql_query(sql, conn)

    # Reverse so charts show oldest → newest (left to right)
    df = df.iloc[::-1].reset_index(drop=True)
    return df
