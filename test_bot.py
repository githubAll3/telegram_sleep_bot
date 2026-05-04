import pytest
import sqlite3
import os
from pathlib import Path
from io import BytesIO
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Test imports
import database
import config
import plot
from bot import parse_duration


# Fixtures
@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing"""
    db_path = tmp_path / "test_sleep.db"
    original_db_path = database.DB_PATH
    database.DB_PATH = db_path
    database.init_db()
    yield db_path
    database.DB_PATH = original_db_path
    if db_path.exists():
        os.remove(db_path)


@pytest.fixture
def temp_config(tmp_path):
    """Create a temporary telegram.conf for testing"""
    config_file = tmp_path / "telegram.conf"
    config_file.write_text("secret = 'test_token_123'\ntimezone = 'Europe/Moscow'\n")
    return config_file


# Tests for parse_duration (bot.py)
class TestParseDuration:
    def test_valid_hours_minutes_cyrillic(self):
        assert parse_duration("1ч 30м") == 90
        assert parse_duration("2ч 15м") == 135
        assert parse_duration("0ч 45м") == 45

    def test_valid_hours_minutes_latin(self):
        assert parse_duration("1h 30m") == 90
        assert parse_duration("2h 15m") == 135

    def test_valid_minutes_only(self):
        assert parse_duration("90м") == 90
        assert parse_duration("90m") == 90
        assert parse_duration("45") == 45

    def test_valid_hours_decimal(self):
        assert parse_duration("1.5ч") == 90
        assert parse_duration("1.5h") == 90
        assert parse_duration("2.25ч") == 135

    def test_combined_formats(self):
        assert parse_duration("1ч 30м 45м") == 135  # 1h + 30m + 45m = 135m
        assert parse_duration("2h 30m") == 150

    def test_invalid_input(self):
        assert parse_duration("invalid") is None
        assert parse_duration("") is None
        assert parse_duration("ч м") is None
        assert parse_duration("-5м") is None


# Tests for config.py
class TestConfig:
    def test_load_config(self, temp_config, monkeypatch):
        monkeypatch.chdir(temp_config.parent)
        with patch('config.CONFIG', {}):
            config.CONFIG = config.load_config()
            config.BOT_TOKEN = config.CONFIG['secret']
            config.TIMEZONE = config.ZoneInfo(config.CONFIG.get('timezone', 'Europe/Moscow'))
            assert config.BOT_TOKEN == 'test_token_123'
            assert str(config.TIMEZONE) == 'Europe/Moscow'

    def test_load_config_default_timezone(self, tmp_path, monkeypatch):
        config_file = tmp_path / "telegram.conf"
        config_file.write_text("secret = 'test_token'\n")
        monkeypatch.chdir(tmp_path)
        with patch('config.CONFIG', {}):
            config.CONFIG = config.load_config()
            config.TIMEZONE = config.ZoneInfo(config.CONFIG.get('timezone', 'Europe/Moscow'))
            assert str(config.TIMEZONE) == 'Europe/Moscow'


# Tests for database.py
class TestDatabase:
    def test_init_db(self, temp_db):
        # Check tables exist
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        assert 'days' in tables
        assert 'sleep_sessions' in tables
        conn.close()

    def test_create_day(self, temp_db):
        start_time = "2026-05-04T12:00:00+00:00"
        day_id = database.create_day(start_time)
        assert isinstance(day_id, int)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT start_time FROM days WHERE id=?", (day_id,))
        row = cursor.fetchone()
        assert row[0] == start_time
        conn.close()

    def test_get_current_day(self, temp_db):
        # No days
        assert database.get_current_day() is None

        # Add first day
        day_id1 = database.create_day("2026-05-04T12:00:00+00:00")
        current = database.get_current_day()
        assert current['id'] == day_id1

        # Add second day
        day_id2 = database.create_day("2026-05-05T12:00:00+00:00")
        current = database.get_current_day()
        assert current['id'] == day_id2

    def test_add_sleep_session(self, temp_db):
        day_id = database.create_day("2026-05-04T12:00:00+00:00")
        sleep_start = "2026-05-04T13:00:00+00:00"
        session_id = database.add_sleep_session(day_id, sleep_start)

        assert isinstance(session_id, int)
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT day_id, sleep_start, sleep_end FROM sleep_sessions WHERE id=?", (session_id,))
        row = cursor.fetchone()
        assert row[0] == day_id
        assert row[1] == sleep_start
        assert row[2] is None  # sleep_end is NULL
        conn.close()

    def test_get_ongoing_sleep_session(self, temp_db):
        day_id = database.create_day("2026-05-04T12:00:00+00:00")
        # No session
        assert database.get_ongoing_sleep_session(day_id) is None

        # Add ongoing session
        session_id = database.add_sleep_session(day_id, "2026-05-04T13:00:00+00:00")
        ongoing = database.get_ongoing_sleep_session(day_id)
        assert ongoing['id'] == session_id

        # Close session
        database.close_sleep_session(session_id, "2026-05-04T14:00:00+00:00", 60, 'day')
        assert database.get_ongoing_sleep_session(day_id) is None

    def test_close_sleep_session(self, temp_db):
        day_id = database.create_day("2026-05-04T12:00:00+00:00")
        session_id = database.add_sleep_session(day_id, "2026-05-04T13:00:00+00:00")

        end_time = "2026-05-04T14:00:00+00:00"
        duration = 60
        database.close_sleep_session(session_id, end_time, duration, 'day')

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT sleep_end, duration_minutes, sleep_type FROM sleep_sessions WHERE id=?", (session_id,))
        row = cursor.fetchone()
        assert row[0] == end_time
        assert row[1] == duration
        assert row[2] == 'day'
        conn.close()

    def test_get_day_sleep_totals(self, temp_db):
        day_id = database.create_day("2026-05-04T12:00:00+00:00")
        # No sessions
        night, day = database.get_day_sleep_totals(day_id)
        assert night == 0
        assert day == 0

        # Add night sleep (8h = 480min)
        s1 = database.add_sleep_session(day_id, "2026-05-04T22:00:00+00:00")
        database.close_sleep_session(s1, "2026-05-05T06:00:00+00:00", 480, 'night')

        # Add day sleep (1.5h = 90min)
        s2 = database.add_sleep_session(day_id, "2026-05-05T13:00:00+00:00")
        database.close_sleep_session(s2, "2026-05-05T14:30:00+00:00", 90, 'day')

        night, day = database.get_day_sleep_totals(day_id)
        assert night == 480
        assert day == 90

    def test_get_7_day_sleep_data(self, temp_db):
        now = datetime.now(timezone.utc)
        # Create 7 days of data
        for i in range(7):
            day_start = (now - timedelta(days=6-i)).isoformat()
            day_id = database.create_day(day_start)

            # Night sleep: 480min (8h)
            night_start = (datetime.fromisoformat(day_start) + timedelta(hours=22)).isoformat()
            night_end = (datetime.fromisoformat(night_start) + timedelta(hours=8)).isoformat()
            s1 = database.add_sleep_session(day_id, night_start)
            database.close_sleep_session(s1, night_end, 480, 'night')

            # Day sleep: 90min (1.5h)
            day_start_sleep = (datetime.fromisoformat(day_start) + timedelta(hours=13)).isoformat()
            day_end_sleep = (datetime.fromisoformat(day_start_sleep) + timedelta(hours=1.5)).isoformat()
            s2 = database.add_sleep_session(day_id, day_start_sleep)
            database.close_sleep_session(s2, day_end_sleep, 90, 'day')

        data = database.get_7_day_sleep_data()
        assert len(data) == 7
        for day_data in data:
            assert day_data['night_min'] == 480
            assert day_data['day_min'] == 90
            assert 'date' in day_data


# Tests for plot.py
class TestPlot:
    def test_generate_sleep_chart(self):
        sleep_data = [
            {'date': '04.05', 'night_min': 480, 'day_min': 90},
            {'date': '05.05', 'night_min': 420, 'day_min': 60},
            {'date': '06.05', 'night_min': 0, 'day_min': 0},
        ]
        buf = plot.generate_sleep_chart(sleep_data)
        assert isinstance(buf, BytesIO)

        # Check PNG header
        buf.seek(0)
        png_data = buf.read()
        assert png_data[:4] == b'\x89PNG'
        buf.close()

    def test_generate_sleep_chart_empty(self):
        buf = plot.generate_sleep_chart([])
        assert isinstance(buf, BytesIO)
        buf.seek(0)
        png_data = buf.read()
        assert png_data[:4] == b'\x89PNG'
        buf.close()
