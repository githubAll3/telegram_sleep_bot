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
        assert parse_duration("1ч 30м 45м") == 135
        assert parse_duration("2h 30m") == 150

    def test_invalid_input(self):
        assert parse_duration("invalid") is None
        assert parse_duration("") is None
        assert parse_duration("ч м") is None
        assert parse_duration("-5м") is None


# Tests for config.py
class TestConfig:
    def test_load_config(self, tmp_path, monkeypatch):
        config_file = tmp_path / "telegram.conf"
        config_file.write_text("secret = 'test_token_123'\ntimezone = 'Europe/Moscow'\n")
        monkeypatch.chdir(tmp_path)
        with patch('config.CONFIG', {}):
            config.CONFIG = config.load_config()
            config.BOT_TOKEN = config.CONFIG['secret']
            config.TIMEZONE = config.ZoneInfo(config.CONFIG.get('timezone', 'Europe/Moscow'))
            assert config.BOT_TOKEN == 'test_token_123'
            assert str(config.TIMEZONE) == 'Europe/Moscow'


# Tests for database.py (multi-child)
class TestDatabaseMultiChild:
    def test_init_db(self, temp_db):
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        assert 'children' in tables
        assert 'shared_access' in tables
        assert 'days' in tables
        assert 'sleep_sessions' in tables
        conn.close()

    def test_add_child(self, temp_db):
        child_id = database.add_child("Иван", 12345)
        assert isinstance(child_id, int)
        child = database.get_child_by_id(child_id)
        assert child['name'] == "Иван"
        assert child['primary_user_id'] == 12345

    def test_get_user_children(self, temp_db):
        database.add_child("Иван", 12345)
        database.add_child("Мария", 12345)
        database.add_child("Петр", 99999)
        children = database.get_user_children(12345)
        assert len(children) == 2
        names = [c['name'] for c in children]
        assert "Иван" in names
        assert "Мария" in names
        assert "Петр" not in names

    def test_share_child(self, temp_db):
        child_id = database.add_child("Иван", 12345)
        # Share with user 54321
        result = database.share_child(child_id, 12345, 54321)
        assert result is True
        # Check shared user can access
        children = database.get_user_children(54321)
        assert len(children) == 1
        assert children[0]['name'] == "Иван"
        # Try sharing again (should fail - duplicate)
        result = database.share_child(child_id, 12345, 54321)
        assert result is False
        # Non-owner tries to share (should fail)
        result = database.share_child(child_id, 99999, 11111)
        assert result is False

    def test_create_day(self, temp_db):
        child_id = database.add_child("Иван", 12345)
        start_time = "2026-05-04T12:00:00+00:00"
        day_id = database.create_day(child_id, start_time)
        assert isinstance(day_id, int)
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT child_id, start_time FROM days WHERE id=?", (day_id,))
        row = cursor.fetchone()
        assert row[0] == child_id
        assert row[1] == start_time
        conn.close()

    def test_get_current_day(self, temp_db):
        child_id = database.add_child("Иван", 12345)
        assert database.get_current_day(child_id) is None
        day_id1 = database.create_day(child_id, "2026-05-04T12:00:00+00:00")
        current = database.get_current_day(child_id)
        assert current['id'] == day_id1
        day_id2 = database.create_day(child_id, "2026-05-05T12:00:00+00:00")
        current = database.get_current_day(child_id)
        assert current['id'] == day_id2

    def test_add_sleep_session(self, temp_db):
        child_id = database.add_child("Иван", 12345)
        day_id = database.create_day(child_id, "2026-05-04T12:00:00+00:00")
        sleep_start = "2026-05-04T13:00:00+00:00"
        session_id = database.add_sleep_session(child_id, day_id, sleep_start)
        assert isinstance(session_id, int)
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT child_id, day_id, sleep_start, sleep_end FROM sleep_sessions WHERE id=?", (session_id,))
        row = cursor.fetchone()
        assert row[0] == child_id
        assert row[1] == day_id
        assert row[2] == sleep_start
        assert row[3] is None
        conn.close()

    def test_get_ongoing_sleep_session(self, temp_db):
        child_id = database.add_child("Иван", 12345)
        day_id = database.create_day(child_id, "2026-05-04T12:00:00+00:00")
        assert database.get_ongoing_sleep_session(child_id, day_id) is None
        session_id = database.add_sleep_session(child_id, day_id, "2026-05-04T13:00:00+00:00")
        ongoing = database.get_ongoing_sleep_session(child_id, day_id)
        assert ongoing['id'] == session_id
        database.close_sleep_session(session_id, "2026-05-04T14:00:00+00:00", 60, 'day')
        assert database.get_ongoing_sleep_session(child_id, day_id) is None

    def test_close_sleep_session(self, temp_db):
        child_id = database.add_child("Иван", 12345)
        day_id = database.create_day(child_id, "2026-05-04T12:00:00+00:00")
        session_id = database.add_sleep_session(child_id, day_id, "2026-05-04T13:00:00+00:00")
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
        child_id = database.add_child("Иван", 12345)
        day_id = database.create_day(child_id, "2026-05-04T12:00:00+00:00")
        night, day = database.get_day_sleep_totals(day_id)
        assert night == 0
        assert day == 0
        s1 = database.add_sleep_session(child_id, day_id, "2026-05-04T22:00:00+00:00")
        database.close_sleep_session(s1, "2026-05-05T06:00:00+00:00", 480, 'night')
        s2 = database.add_sleep_session(child_id, day_id, "2026-05-05T13:00:00+00:00")
        database.close_sleep_session(s2, "2026-05-05T14:30:00+00:00", 90, 'day')
        night, day = database.get_day_sleep_totals(day_id)
        assert night == 480
        assert day == 90

    def test_get_7_day_sleep_data(self, temp_db):
        child_id = database.add_child("Иван", 12345)
        now = datetime.now(timezone.utc)
        for i in range(7):
            day_start = (now - timedelta(days=6-i)).isoformat()
            day_id = database.create_day(child_id, day_start)
            night_start = (datetime.fromisoformat(day_start) + timedelta(hours=22)).isoformat()
            night_end = (datetime.fromisoformat(night_start) + timedelta(hours=8)).isoformat()
            s1 = database.add_sleep_session(child_id, day_id, night_start)
            database.close_sleep_session(s1, night_end, 480, 'night')
            day_start_sleep = (datetime.fromisoformat(day_start) + timedelta(hours=13)).isoformat()
            day_end_sleep = (datetime.fromisoformat(day_start_sleep) + timedelta(hours=1.5)).isoformat()
            s2 = database.add_sleep_session(child_id, day_id, day_start_sleep)
            database.close_sleep_session(s2, day_end_sleep, 90, 'day')
        data = database.get_7_day_sleep_data(child_id)
        assert len(data) == 7
        for day_data in data:
            assert day_data['night_min'] == 480
            assert day_data['day_min'] == 90
            assert 'date' in day_data

    def test_get_child_name(self, temp_db):
        child_id = database.add_child("Иван", 12345)
        name = database.get_child_name(child_id)
        assert name == "Иван"


# Tests for plot.py
class TestPlot:
    def test_generate_sleep_chart(self):
        sleep_data = [
            {'date': '04.05', 'night_min': 480, 'day_min': 90},
            {'date': '05.05', 'night_min': 420, 'day_min': 60},
            {'date': '06.05', 'night_min': 0, 'day_min': 0},
        ]
        buf = plot.generate_sleep_chart(sleep_data, "Иван")
        assert isinstance(buf, BytesIO)
        buf.seek(0)
        png_data = buf.read()
        assert png_data[:4] == b'\x89PNG'
        buf.close()

    def test_generate_sleep_chart_empty(self):
        buf = plot.generate_sleep_chart([], "Иван")
        assert isinstance(buf, BytesIO)
        buf.seek(0)
        png_data = buf.read()
        assert png_data[:4] == b'\x89PNG'
        buf.close()
