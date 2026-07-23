"""Tests for fetch_schedule.py"""
import json
import os
import tempfile
import datetime
from unittest.mock import patch, mock_open

import fetch_schedule as fs

CHINA_TZ = datetime.timezone(datetime.timedelta(hours=8))


# --- build_reminders ----------------------------------------------------

def test_build_reminders():
    r = fs.build_reminders("08:30", "10:00")
    times = [x["time"] for x in r]
    # First class start 08:30 → offsets -15, -10, -5, 0
    assert "08:15" in times
    assert "08:20" in times
    assert "08:25" in times
    assert "08:30" in times
    # Last class end 10:00 → offsets 0, 5, 10, 15
    assert "10:00" in times
    assert "10:05" in times
    assert "10:10" in times
    assert "10:15" in times
    assert len(r) == 8
    for item in r:
        assert item["label"] == "GEDU打卡"
        assert item["body"] == "GEDU打卡"


def test_build_reminders_midnight_boundary():
    """Reminders near midnight should wrap correctly."""
    r = fs.build_reminders("23:50", "23:55")
    times = [x["time"] for x in r]
    assert "23:35" in times
    assert "23:40" in times
    assert "23:45" in times
    assert "23:50" in times
    assert "23:55" in times
    assert "00:00" in times
    assert "00:05" in times
    assert "00:10" in times


def test_build_reminders_early_morning():
    r = fs.build_reminders("08:00", "08:00")
    times = [x["time"] for x in r]
    assert "07:45" in times
    assert "08:00" in times
    assert "08:05" in times


# --- scan_and_cache -----------------------------------------------------

def _mock_now():
    return datetime.datetime(2026, 7, 24, 15, 0, 0, tzinfo=CHINA_TZ)


def test_scan_finds_class_on_first_day(tmp_path, monkeypatch):
    """Tomorrow has classes — should return immediately."""
    monkeypatch.setattr(fs, "CACHE_FILE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(fs, "now_china", _mock_now)

    def mock_fetch(date_str):
        if date_str == "2026-07-25":
            return [{"start": "08:30", "end": "10:00"}]
        return []

    monkeypatch.setattr(fs, "fetch_schedule", mock_fetch)

    class_date, reminders, empty = fs.scan_and_cache("2026-07-25")

    assert class_date == "2026-07-25"
    assert len(reminders) == 8
    assert empty == []

    cache = json.loads(tmp_path.joinpath("cache.json").read_text())
    assert "2026-07-25" in cache
    assert isinstance(cache["2026-07-25"], list)
    assert len(cache["2026-07-25"]) == 8


def test_scan_skips_empty_days(tmp_path, monkeypatch):
    """Tomorrow empty, next day has classes."""
    monkeypatch.setattr(fs, "CACHE_FILE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(fs, "now_china", _mock_now)

    call_count = [0]

    def mock_fetch(date_str):
        call_count[0] += 1
        if date_str == "2026-07-25":
            return []   # Saturday, no class
        if date_str == "2026-07-26":
            return []   # Sunday, no class
        if date_str == "2026-07-27":
            return [{"start": "08:30", "end": "10:00"}]  # Monday
        return []

    monkeypatch.setattr(fs, "fetch_schedule", mock_fetch)

    class_date, reminders, empty = fs.scan_and_cache("2026-07-25")

    assert class_date == "2026-07-27"
    assert len(reminders) == 8
    assert empty == ["2026-07-25", "2026-07-26"]
    assert call_count[0] == 3  # stopped after finding class

    cache = json.loads(tmp_path.joinpath("cache.json").read_text())
    assert cache["2026-07-25"] is None
    assert cache["2026-07-26"] is None
    assert isinstance(cache["2026-07-27"], list)


def test_scan_all_empty(tmp_path, monkeypatch):
    """All 7 days empty — should return [], empty_dates has 7 entries."""
    monkeypatch.setattr(fs, "CACHE_FILE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(fs, "now_china", _mock_now)

    def mock_fetch(date_str):
        return []

    monkeypatch.setattr(fs, "fetch_schedule", mock_fetch)

    class_date, reminders, empty = fs.scan_and_cache("2026-07-25")

    assert class_date is None
    assert reminders == []
    assert len(empty) == 7
    assert "2026-07-25" in empty
    assert "2026-07-31" in empty

    cache = json.loads(tmp_path.joinpath("cache.json").read_text())
    for d in empty:
        assert cache[d] is None


def test_scan_api_error_aborts(tmp_path, monkeypatch):
    """API error on second day should abort, caching only scanned empty days."""
    monkeypatch.setattr(fs, "CACHE_FILE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(fs, "now_china", _mock_now)

    def mock_fetch(date_str):
        if date_str == "2026-07-25":
            return []   # empty
        if date_str == "2026-07-26":
            return None  # API error!

    monkeypatch.setattr(fs, "fetch_schedule", mock_fetch)

    class_date, reminders, empty = fs.scan_and_cache("2026-07-25")

    assert class_date is None
    assert reminders is None  # None means API error
    assert empty == ["2026-07-25"]

    cache = json.loads(tmp_path.joinpath("cache.json").read_text())
    assert cache["2026-07-25"] is None
    assert "2026-07-26" not in cache


def test_scan_cleans_old_entries(tmp_path, monkeypatch):
    """Entries before today should be removed from cache."""
    monkeypatch.setattr(fs, "CACHE_FILE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(fs, "now_china", _mock_now)

    # Pre-populate cache with old entry + today's entry
    tmp_path.joinpath("cache.json").write_text(json.dumps({
        "2026-07-23": [{"time": "08:15", "label": "x", "body": "x"}],
        "2026-07-24": [{"time": "10:00", "label": "y", "body": "y"}],
    }))

    def mock_fetch(date_str):
        return [{"start": "08:30", "end": "10:00"}]

    monkeypatch.setattr(fs, "fetch_schedule", mock_fetch)

    fs.scan_and_cache("2026-07-25")

    cache = json.loads(tmp_path.joinpath("cache.json").read_text())
    assert "2026-07-23" not in cache  # yesterday cleaned out
    assert "2026-07-24" in cache      # today still preserved
    assert "2026-07-25" in cache      # new data


def test_scan_respects_max_days_param(tmp_path, monkeypatch):
    """max_days=3 should only scan 3 days."""
    monkeypatch.setattr(fs, "CACHE_FILE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(fs, "now_china", _mock_now)

    call_count = [0]

    def mock_fetch(date_str):
        call_count[0] += 1
        return []

    monkeypatch.setattr(fs, "fetch_schedule", mock_fetch)

    _, _, empty = fs.scan_and_cache("2026-07-25", max_days=3)
    assert len(empty) == 3
    assert call_count[0] == 3


# --- load_cache / save_cache --------------------------------------------

def test_load_cache_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "CACHE_FILE", "/nonexistent/cache.json")
    assert fs.load_cache() == {}


def test_save_and_load_cache(tmp_path, monkeypatch):
    p = str(tmp_path / "cache.json")
    monkeypatch.setattr(fs, "CACHE_FILE", p)
    fs.save_cache({"2026-07-25": [{"time": "08:00", "label": "t", "body": "b"}]})
    assert fs.load_cache() == {"2026-07-25": [{"time": "08:00", "label": "t", "body": "b"}]}
