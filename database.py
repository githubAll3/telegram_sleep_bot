import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DB_DIR = Path(__file__).parent / "data"
DB_PATH = DB_DIR / "sleep.db"

def init_db():
    DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sleep_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_id INTEGER NOT NULL,
            sleep_start TEXT NOT NULL,
            sleep_end TEXT,
            duration_minutes INTEGER,
            sleep_type TEXT CHECK(sleep_type IN ('night', 'day')),
            FOREIGN KEY (day_id) REFERENCES days(id)
        )
    ''')
    conn.commit()
    conn.close()

def create_day(start_time_utc: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO days (start_time) VALUES (?)', (start_time_utc,))
    day_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return day_id

def get_current_day():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, start_time FROM days ORDER BY start_time DESC LIMIT 1')
    row = cursor.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'start_time': row[1]}
    return None

def add_sleep_session(day_id: int, sleep_start_utc: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO sleep_sessions (day_id, sleep_start) VALUES (?, ?)', (day_id, sleep_start_utc))
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return session_id

def get_ongoing_sleep_session(day_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, sleep_start FROM sleep_sessions WHERE day_id = ? AND sleep_end IS NULL LIMIT 1', (day_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'sleep_start': row[1]}
    return None

def close_sleep_session(session_id: int, sleep_end_utc: str, duration_minutes: int, sleep_type: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE sleep_sessions SET sleep_end = ?, duration_minutes = ?, sleep_type = ? WHERE id = ?',
                   (sleep_end_utc, duration_minutes, sleep_type, session_id))
    conn.commit()
    conn.close()

def get_day_sleep_totals(day_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT sleep_type, SUM(duration_minutes) FROM sleep_sessions WHERE day_id = ? AND sleep_type IS NOT NULL GROUP BY sleep_type', (day_id,))
    rows = cursor.fetchall()
    conn.close()
    night = 0
    day = 0
    for row in rows:
        if row[0] == 'night':
            night = row[1] or 0
        elif row[0] == 'day':
            day = row[1] or 0
    return night, day

def get_7_day_sleep_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, start_time FROM days ORDER BY start_time DESC LIMIT 7')
    days = cursor.fetchall()
    days.reverse()
    data = []
    for day_id, start_time_utc in days:
        dt_utc = datetime.fromisoformat(start_time_utc)
        dt_msk = dt_utc.astimezone(ZoneInfo('Europe/Moscow'))
        date_str = dt_msk.strftime('%d.%m')
        cursor.execute('SELECT sleep_type, SUM(duration_minutes) FROM sleep_sessions WHERE day_id = ? AND sleep_type IS NOT NULL GROUP BY sleep_type', (day_id,))
        rows = cursor.fetchall()
        night_min = 0
        day_min = 0
        for row in rows:
            if row[0] == 'night':
                night_min = row[1] or 0
            elif row[0] == 'day':
                day_min = row[1] or 0
        data.append({
            'date': date_str,
            'night_min': night_min,
            'day_min': day_min
        })
    conn.close()
    return data
