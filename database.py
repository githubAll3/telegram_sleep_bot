import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_DIR = Path(__file__).parent / "data"
DB_PATH = DB_DIR / "sleep.db"

def init_db():
    DB_DIR.mkdir(exist_ok=True)

    # Check if we need to recreate the database
    recreate = False
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(days)")
            columns = [row[1] for row in cursor.fetchall()]
            conn.close()
            if 'child_id' not in columns:
                recreate = True
        except Exception:
            recreate = True

    if recreate:
        DB_PATH.unlink(missing_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS children (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            primary_user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shared_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            child_id INTEGER NOT NULL,
            shared_user_id INTEGER NOT NULL,
            FOREIGN KEY (child_id) REFERENCES children(id) ON DELETE CASCADE,
            UNIQUE(child_id, shared_user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            child_id INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            FOREIGN KEY (child_id) REFERENCES children(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sleep_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            child_id INTEGER NOT NULL,
            day_id INTEGER NOT NULL,
            sleep_start TEXT NOT NULL,
            sleep_end TEXT,
            duration_minutes INTEGER,
            sleep_type TEXT CHECK(sleep_type IN ('night', 'day')),
            FOREIGN KEY (child_id) REFERENCES children(id) ON DELETE CASCADE,
            FOREIGN KEY (day_id) REFERENCES days(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    conn.close()

def add_child(name: str, primary_user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO children (name, primary_user_id, created_at) VALUES (?, ?, ?)',
                   (name, primary_user_id, datetime.now(timezone.utc).isoformat()))
    child_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return child_id

def get_user_children(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.* FROM children c
        LEFT JOIN shared_access s ON c.id = s.child_id
        WHERE c.primary_user_id = ? OR s.shared_user_id = ?
        GROUP BY c.id
        ORDER BY c.name
    ''', (user_id, user_id))
    rows = cursor.fetchall()
    conn.close()
    return [{'id': row[0], 'name': row[1], 'primary_user_id': row[2]} for row in rows]

def get_child_by_id(child_id: int, user_id: int = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if user_id:
        cursor.execute('''
            SELECT c.* FROM children c
            LEFT JOIN shared_access s ON c.id = s.child_id
            WHERE c.id = ? AND (c.primary_user_id = ? OR s.shared_user_id = ?)
        ''', (child_id, user_id, user_id))
    else:
        cursor.execute('SELECT * FROM children WHERE id = ?', (child_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'name': row[1], 'primary_user_id': row[2]}
    return None

def share_child(child_id: int, owner_user_id: int, shared_user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM children WHERE id = ? AND primary_user_id = ?', (child_id, owner_user_id))
    if not cursor.fetchone():
        conn.close()
        return False
    try:
        cursor.execute('INSERT INTO shared_access (child_id, shared_user_id) VALUES (?, ?)',
                       (child_id, shared_user_id))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def create_day(child_id: int, start_time_utc: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO days (child_id, start_time) VALUES (?, ?)', (child_id, start_time_utc))
    day_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return day_id

def get_current_day(child_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, start_time FROM days WHERE child_id = ? ORDER BY start_time DESC LIMIT 1', (child_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'start_time': row[1]}
    return None

def add_sleep_session(child_id: int, day_id: int, sleep_start_utc: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO sleep_sessions (child_id, day_id, sleep_start) VALUES (?, ?, ?)',
                   (child_id, day_id, sleep_start_utc))
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return session_id

def get_ongoing_sleep_session(child_id: int, day_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, sleep_start FROM sleep_sessions WHERE child_id = ? AND day_id = ? AND sleep_end IS NULL LIMIT 1',
                   (child_id, day_id))
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

def get_7_day_sleep_data(child_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, start_time FROM days WHERE child_id = ? ORDER BY start_time DESC LIMIT 7', (child_id,))
    days = cursor.fetchall()
    days.reverse()
    data = []
    for day_id, start_time_utc in days:
        from zoneinfo import ZoneInfo
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

def get_child_name(child_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM children WHERE id = ?', (child_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None
