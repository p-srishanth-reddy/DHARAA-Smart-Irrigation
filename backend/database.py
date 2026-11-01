import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), "dharaa.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        timezone TEXT DEFAULT 'Asia/Kolkata',
        units TEXT DEFAULT 'metric',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS farms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        state_district TEXT,
        village_locality TEXT,
        mandal_taluk TEXT,
        district TEXT,
        state TEXT,
        timezone TEXT DEFAULT 'Asia/Kolkata',
        lat REAL,
        lon REAL,
        area REAL DEFAULT 1.0,
        area_unit TEXT DEFAULT 'acre',
        crop TEXT DEFAULT 'Wheat',
        soil_type TEXT DEFAULT 'Loamy',
        season TEXT DEFAULT 'Rabi',
        water_source TEXT DEFAULT 'Borewell',
        archived INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
        name TEXT DEFAULT 'DHARAA-ESP32-Node-1',
        key_hash TEXT NOT NULL,
        last_seen TIMESTAMP,
        firmware_version TEXT DEFAULT 'v1.0.0-MicroPython',
        status TEXT DEFAULT 'offline'
    );

    CREATE TABLE IF NOT EXISTS telemetry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        moisture REAL,
        temperature REAL,
        humidity REAL,
        rain INTEGER,
        flow_pulses INTEGER,
        pump_state INTEGER DEFAULT 0,
        sensor_status TEXT DEFAULT 'OK'
    );

    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        start_time TEXT NOT NULL,
        target_moisture REAL DEFAULT 45.0,
        runtime_limit INTEGER DEFAULT 300,
        status TEXT DEFAULT 'active',
        notes TEXT,
        last_run_date TEXT,
        last_run_at TIMESTAMP,
        last_run_status TEXT
    );

    CREATE TABLE IF NOT EXISTS irrigation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ended_at TIMESTAMP,
        trigger_source TEXT DEFAULT 'auto',
        estimated_litres REAL,
        status TEXT DEFAULT 'running',
        stop_reason TEXT
    );

    CREATE TABLE IF NOT EXISTS commands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        type TEXT NOT NULL,
        payload TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        delivered_at TIMESTAMP,
        acknowledged_at TIMESTAMP,
        status TEXT DEFAULT 'pending'
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        message TEXT NOT NULL,
        severity TEXT DEFAULT 'info',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        read_at TIMESTAMP
    );
    """)

    # Ensure schedules table has new execution tracking columns
    sched_cols = [c[1] for c in cursor.execute("PRAGMA table_info(schedules)").fetchall()]
    if "last_run_date" not in sched_cols:
        cursor.execute("ALTER TABLE schedules ADD COLUMN last_run_date TEXT")
    if "last_run_at" not in sched_cols:
        cursor.execute("ALTER TABLE schedules ADD COLUMN last_run_at TIMESTAMP")
    if "last_run_status" not in sched_cols:
        cursor.execute("ALTER TABLE schedules ADD COLUMN last_run_status TEXT")

    # Ensure farms table has location hierarchy and timezone columns
    farm_cols = [c[1] for c in cursor.execute("PRAGMA table_info(farms)").fetchall()]
    if "village_locality" not in farm_cols:
        cursor.execute("ALTER TABLE farms ADD COLUMN village_locality TEXT")
    if "mandal_taluk" not in farm_cols:
        cursor.execute("ALTER TABLE farms ADD COLUMN mandal_taluk TEXT")
    if "district" not in farm_cols:
        cursor.execute("ALTER TABLE farms ADD COLUMN district TEXT")
    if "state" not in farm_cols:
        cursor.execute("ALTER TABLE farms ADD COLUMN state TEXT")
    if "timezone" not in farm_cols:
        cursor.execute("ALTER TABLE farms ADD COLUMN timezone TEXT DEFAULT 'Asia/Kolkata'")

    # Backfill default values for existing farms missing location breakdown
    cursor.execute("""
        UPDATE farms
        SET village_locality = COALESCE(village_locality, 'Sultan Bazar'),
            mandal_taluk = COALESCE(mandal_taluk, 'Nampally mandal'),
            district = COALESCE(district, 'Hyderabad'),
            state = COALESCE(state, 'Telangana'),
            timezone = COALESCE(timezone, 'Asia/Kolkata')
        WHERE id = 1 AND (village_locality IS NULL OR timezone IS NULL)
    """)

    # Check if default user exists, if not seed initial demo data
    user = cursor.execute("SELECT id FROM users WHERE username = 'farmer'").fetchone()
    if not user:
        pwd_hash = generate_password_hash("dharaa123")
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, timezone, units)
            VALUES ('farmer', 'farmer@dharaa.org', ?, 'Asia/Kolkata', 'metric')
        """, (pwd_hash,))
        user_id = cursor.lastrowid

        # Seed sample farm (Hyderabad / Telangana coordinates as baseline)
        cursor.execute("""
            INSERT INTO farms (user_id, name, state_district, village_locality, mandal_taluk, district, state, timezone, lat, lon, area, area_unit, crop, soil_type, season, water_source)
            VALUES (?, 'DHARAA Experimental Farm', 'Hyderabad, Telangana', 'Sultan Bazar', 'Nampally mandal', 'Hyderabad', 'Telangana', 'Asia/Kolkata', 17.3850, 78.4867, 2.5, 'acre', 'Cotton', 'Black Cotton Soil', 'Kharif', 'Borewell')
        """, (user_id,))
        farm_id = cursor.lastrowid

        # Seed sample device with default API key hash
        # Default device key for development: 'dharaa-esp32-secret-2026'
        dev_key_hash = generate_password_hash("dharaa-esp32-secret-2026")
        cursor.execute("""
            INSERT INTO devices (farm_id, name, key_hash, status, firmware_version)
            VALUES (?, 'ESP32 Field Node 01', ?, 'online', 'v1.0.0-MicroPython')
        """, (farm_id, dev_key_hash))
        dev_id = cursor.lastrowid

        # Seed default schedule
        cursor.execute("""
            INSERT INTO schedules (farm_id, name, start_time, target_moisture, runtime_limit, status, notes)
            VALUES (?, 'Morning Critical Irrigation', '06:00', 45.0, 300, 'active', 'Pre-dawn soil recharge before high evapotranspiration')
        """, (farm_id,))

        # Seed initial notification
        cursor.execute("""
            INSERT INTO notifications (user_id, message, severity)
            VALUES (?, 'Welcome to DHARAA Smart Irrigation System! Hardware node registered and ready.', 'info')
        """, (user_id,))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at:", DB_PATH)
