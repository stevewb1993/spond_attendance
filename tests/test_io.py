"""Tests for spond_attendance.io module."""

from datetime import date
from pathlib import Path

import pytest

from spond_attendance.io import (
    discover_files,
    find_new_files,
    load_state,
    parse_file_date,
    save_state,
)


# ---------------------------------------------------------------------------
# parse_file_date
# ---------------------------------------------------------------------------


class TestParseFileDate:
    def test_valid_filename(self):
        path = Path("spond_attendance_jan_25.xlsx")
        assert parse_file_date(path) == date(2025, 1, 1)

    def test_sept_variant(self):
        path = Path("spond_attendance_sept_24.xlsx")
        assert parse_file_date(path) == date(2024, 9, 1)

    def test_case_insensitive(self):
        path = Path("spond_attendance_JAN_25.xlsx")
        assert parse_file_date(path) == date(2025, 1, 1)

    def test_bad_pattern_raises(self):
        with pytest.raises(ValueError, match="does not match expected pattern"):
            parse_file_date(Path("test.xlsx"))

    def test_bad_month_raises(self):
        with pytest.raises(ValueError, match="Unrecognized month abbreviation"):
            parse_file_date(Path("spond_attendance_xyz_25.xlsx"))


# ---------------------------------------------------------------------------
# discover_files
# ---------------------------------------------------------------------------


class TestDiscoverFiles:
    def test_sorted_oldest_first(self, tmp_path: Path):
        # Create files out of chronological order.
        names = [
            "spond_attendance_mar_25.xlsx",
            "spond_attendance_jan_25.xlsx",
            "spond_attendance_feb_25.xlsx",
        ]
        for name in names:
            (tmp_path / name).touch()

        result = discover_files(tmp_path)
        assert [f.name for f in result] == [
            "spond_attendance_jan_25.xlsx",
            "spond_attendance_feb_25.xlsx",
            "spond_attendance_mar_25.xlsx",
        ]

    def test_raises_on_unexpected_xlsx(self, tmp_path: Path):
        (tmp_path / "spond_attendance_jan_25.xlsx").touch()
        (tmp_path / "random_report.xlsx").touch()

        with pytest.raises(ValueError, match="Unexpected xlsx file"):
            discover_files(tmp_path)

    def test_ignores_temp_files(self, tmp_path: Path):
        (tmp_path / "spond_attendance_jan_25.xlsx").touch()
        (tmp_path / "~$spond_attendance_jan_25.xlsx").touch()

        result = discover_files(tmp_path)
        assert len(result) == 1
        assert result[0].name == "spond_attendance_jan_25.xlsx"

    def test_empty_directory(self, tmp_path: Path):
        assert discover_files(tmp_path) == []


# ---------------------------------------------------------------------------
# load_state / save_state
# ---------------------------------------------------------------------------


class TestState:
    def test_round_trip(self, tmp_path: Path):
        files = {"spond_attendance_jan_25.xlsx", "spond_attendance_feb_25.xlsx"}
        save_state(tmp_path, files)
        loaded = load_state(tmp_path)
        assert loaded == files

    def test_load_returns_empty_set_when_no_file(self, tmp_path: Path):
        assert load_state(tmp_path) == set()


# ---------------------------------------------------------------------------
# find_new_files
# ---------------------------------------------------------------------------


class TestFindNewFiles:
    def test_filters_processed(self):
        files = [
            Path("spond_attendance_jan_25.xlsx"),
            Path("spond_attendance_feb_25.xlsx"),
            Path("spond_attendance_mar_25.xlsx"),
        ]
        processed = {"spond_attendance_jan_25.xlsx", "spond_attendance_feb_25.xlsx"}

        result = find_new_files(files, processed)
        assert result == [Path("spond_attendance_mar_25.xlsx")]

    def test_returns_all_when_none_processed(self):
        files = [
            Path("spond_attendance_jan_25.xlsx"),
            Path("spond_attendance_feb_25.xlsx"),
        ]
        result = find_new_files(files, set())
        assert result == files
